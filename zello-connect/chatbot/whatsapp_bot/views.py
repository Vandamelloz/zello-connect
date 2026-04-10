import os
import json
import requests
import tempfile
from dotenv import load_dotenv
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from groq import Groq

# Carrega as variáveis do ambiente
load_dotenv()

# --- CHAVES DO SISTEMA ---
CHATWOOT_ACCOUNT_ID = os.getenv("CHATWOOT_ACCOUNT_ID")
CHATWOOT_API_TOKEN = os.getenv("CHATWOOT_API_TOKEN")
CHATWOOT_INBOX_ID = int(os.getenv("CHATWOOT_INBOX_ID", 0))
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OCR_API_KEY = os.getenv("OCR_API_KEY")

CHATWOOT_URL = "https://app.chatwoot.com/api/v1"
WAHA_URL = "http://localhost:3000"

HEADERS = {
    "api_access_token": CHATWOOT_API_TOKEN,
    "Content-Type": "application/json"
}

# Inicializa o cliente da Groq se a chave existir
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

def buscar_ou_criar_contato(remetente_completo):
    url_busca = f"{CHATWOOT_URL}/accounts/{CHATWOOT_ACCOUNT_ID}/contacts/search?q={remetente_completo}"
    res_busca = requests.get(url_busca, headers=HEADERS).json()
    
    if res_busca.get('payload') and len(res_busca['payload']) > 0:
        return res_busca['payload'][0]['id']
        
    url_cria = f"{CHATWOOT_URL}/accounts/{CHATWOOT_ACCOUNT_ID}/contacts"
    dados = {"name": f"Paciente {remetente_completo[:8]}...", "identifier": remetente_completo}
    res_cria = requests.post(url_cria, headers=HEADERS, json=dados).json()
    return res_cria['payload']['contact']['id']

def buscar_ou_criar_conversa(contact_id):
    url_busca = f"{CHATWOOT_URL}/accounts/{CHATWOOT_ACCOUNT_ID}/contacts/{contact_id}/conversations"
    res_busca = requests.get(url_busca, headers=HEADERS).json()
    
    for conv in res_busca.get('payload', []):
        if conv.get('inbox_id') == CHATWOOT_INBOX_ID and conv.get('status') == 'open':
            return conv['id'], False
            
    url_cria = f"{CHATWOOT_URL}/accounts/{CHATWOOT_ACCOUNT_ID}/conversations"
    dados = {"inbox_id": CHATWOOT_INBOX_ID, "contact_id": contact_id}
    res_cria = requests.post(url_cria, headers=HEADERS, json=dados).json()
    return res_cria['id'], True

# --- 1. FUNÇÃO DE IA PARA ÁUDIO ---
def baixar_e_transcrever_audio(media_url):
    try:
        print(f"📥 Tentando baixar áudio...")
        res = requests.get(media_url)
        if res.status_code == 200:
            tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".ogg")
            tmp_file.write(res.content)
            tmp_file.close()
            texto_transcrito = "[Transcrição Indisponível]"
            
            if groq_client:
                print("🧠 Enviando áudio para a Groq Whisper...")
                with open(tmp_file.name, "rb") as audio_file:
                    transcription = groq_client.audio.transcriptions.create(
                        file=("audio.ogg", audio_file.read()), model="whisper-large-v3", language="pt"
                    )
                    texto_transcrito = transcription.text
            return {"texto": texto_transcrito, "caminho": tmp_file.name, "tipo_arquivo": "audio/ogg", "nome": "audio.ogg"}
    except Exception as e:
        print(f"❌ Erro Crítico na IA de Áudio: {e}")
    return None

# --- 2. FUNÇÃO DE VISÃO COMPUTACIONAL (OCR AVANÇADO) ---
def baixar_e_ler_imagem(media_url):
    try:
        print(f"📥 Tentando baixar imagem...")
        res = requests.get(media_url)
        if res.status_code == 200:
            tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            tmp_file.write(res.content)
            tmp_file.close()
            texto_extraido = "[Nenhum texto legível encontrado na imagem]"
            
            if OCR_API_KEY:
                print("👁️ Enviando imagem para leitura (OCR.space - Motor Avançado)...")
                with open(tmp_file.name, 'rb') as img_file:
                    resposta_ocr = requests.post(
                        'https://api.ocr.space/parse/image',
                        files={'file': img_file},
                        data={
                            'apikey': OCR_API_KEY, 
                            'language': 'por',
                            'OCREngine': '2',  # Motor 2: Melhor para caracteres difíceis e manuscritos
                            'scale': 'true'    # Melhora a resolução da foto
                        }
                    ).json()
                    
                    if not resposta_ocr.get('IsErroredOnProcessing'):
                        resultados = resposta_ocr.get('ParsedResults', [])
                        if resultados and resultados[0].get('ParsedText'):
                            texto_extraido = resultados[0]['ParsedText'].strip()
            return {"texto": texto_extraido, "caminho": tmp_file.name, "tipo_arquivo": "image/jpeg", "nome": "exame.jpg"}
    except Exception as e:
        print(f"❌ Erro Crítico no OCR: {e}")
    return None

@csrf_exempt
def waha_webhook(request):
    """VIA DE IDA: WAHA -> Django -> Chatwoot"""
    if request.method == 'POST':
        try:
            payload = json.loads(request.body)
            event_type = payload.get('event')
            
            if event_type in ['message', 'message.any']:
                data = payload.get('payload', {})
                mensagem_texto = data.get('body', '')
                remetente_completo = data.get('from', '')
                
                # BUSCANDO DADOS DO PACOTE
                _data_interna = data.get('_data', {})
                msg_type = _data_interna.get('type', '')
                mimetype = data.get('media', {}).get('mimetype', '')
                media_url = data.get('media', {}).get('url', '')
                
                dados_midia = None
                
                # --- TRIAGEM DE ACESSIBILIDADE ---
                if data.get('hasMedia'):
                    if msg_type in ['ptt', 'audio', 'voice'] or 'audio' in mimetype:
                        print("\n🎙️ [IA] Áudio detectado no pacote!")
                        dados_midia = baixar_e_transcrever_audio(media_url)
                        if dados_midia:
                            mensagem_texto = f"🎙️ *[Áudio do Paciente]*\n*Transcrição:* {dados_midia['texto']}"
                    
                    elif msg_type == 'image' or 'image' in mimetype:
                        print("\n🖼️ [IA] Imagem/Exame detectado no pacote!")
                        dados_midia = baixar_e_ler_imagem(media_url)
                        if dados_midia:
                            mensagem_texto = f"🖼️ *[Documento Enviado]*\n*Texto Extraído da Imagem:* \n{dados_midia['texto']}"
                
                # Ignorar se não tiver texto nenhum nem mídia
                if not mensagem_texto and not dados_midia:
                    return JsonResponse({"status": "ignorado sem texto/midia"}, status=200)

                contact_id = buscar_ou_criar_contato(remetente_completo)
                conversation_id, conversa_nova = buscar_ou_criar_conversa(contact_id)
                url_msg = f"{CHATWOOT_URL}/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conversation_id}/messages"
                
                # --- MÁGICA DO ENVIO UNIVERSAL (TEXTO / ÁUDIO / IMAGEM) ---
                if dados_midia and dados_midia.get('caminho'):
                    cabecalhos_arquivo = {"api_access_token": CHATWOOT_API_TOKEN} 
                    dados_texto = {
                        "content": mensagem_texto,
                        "message_type": "incoming",
                        "private": "false"
                    }
                    try:
                        with open(dados_midia['caminho'], 'rb') as f:
                            arquivos = [('attachments[]', (dados_midia['nome'], f, dados_midia['tipo_arquivo']))]
                            requests.post(url_msg, headers=cabecalhos_arquivo, data=dados_texto, files=arquivos)
                    finally:
                        if os.path.exists(dados_midia['caminho']):
                            os.remove(dados_midia['caminho'])
                else:
                    dados_msg = {
                        "content": f"*[Paciente]*\n{mensagem_texto}",
                        "message_type": "incoming",
                        "private": False
                    }
                    requests.post(url_msg, headers=HEADERS, json=dados_msg)

                # Robô de Triagem Inicial
                if conversa_nova:
                    msg_robo = "🤖 *Zello Connect:* Olá! Sou o assistente virtual do hospital. Para agilizar seu atendimento, por favor, me diga seu *nome completo* e o que precisa hoje?"
                    requests.post(f"{WAHA_URL}/api/sendText", json={
                        "chatId": remetente_completo, "text": msg_robo, "session": "default"
                    })

            return JsonResponse({"status": "recebido"}, status=200)

        except Exception as e:
            print(f"Erro na IDA: {e}")
            return JsonResponse({"erro": str(e)}, status=500)
            
    return JsonResponse({"erro": "Apenas POST"}, status=405)

@csrf_exempt
def chatwoot_webhook(request):
    """VIA DE VOLTA: Chatwoot -> Django -> WAHA"""
    if request.method == 'POST':
        try:
            payload = json.loads(request.body)
            evento = payload.get('event')
            tipo = payload.get('message_type')
            conteudo = payload.get('content', '')
            
            if evento == 'message_created' and tipo == 'outgoing':
                remetente_completo = payload.get('conversation', {}).get('meta', {}).get('sender', {}).get('identifier')
                if remetente_completo:
                    requests.post(f"{WAHA_URL}/api/sendText", json={"chatId": remetente_completo, "text": conteudo, "session": "default"})
            return JsonResponse({"status": "recebido"}, status=200)
        except Exception as e:
            return JsonResponse({"erro": str(e)}, status=500)
    return JsonResponse({"erro": "Apenas POST"}, status=405)