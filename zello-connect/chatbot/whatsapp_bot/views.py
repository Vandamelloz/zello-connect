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

# --- CHAVES E CONFIGURAÇÕES ---
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

# Inicializa o cliente da Groq
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Memória RAM para o histórico do Chat (MVP)
HISTORICO_MEMORIA = {}

# ==========================================
# 1. INTEGRAÇÃO CHATWOOT (Contatos e Conversas)
# ==========================================
def buscar_contato_e_conversa(fone):
    try:
        # Busca ou cria o contato
        res = requests.get(f"{CHATWOOT_URL}/accounts/{CHATWOOT_ACCOUNT_ID}/contacts/search?q={fone}", headers=HEADERS).json()
        payload_busca = res.get('payload') or []
        
        if payload_busca:
            c_id = payload_busca[0].get('id')
        else:
            res_cria = requests.post(f"{CHATWOOT_URL}/accounts/{CHATWOOT_ACCOUNT_ID}/contacts", headers=HEADERS, json={"name": f"Paciente {fone[:8]}", "identifier": fone}).json()
            c_id = res_cria.get('payload', {}).get('contact', {}).get('id')
        
        # Busca ou cria a conversa aberta
        res_c = requests.get(f"{CHATWOOT_URL}/accounts/{CHATWOOT_ACCOUNT_ID}/contacts/{c_id}/conversations", headers=HEADERS).json()
        lista_conversas = res_c.get('payload') or []
        for conv in lista_conversas:
            if conv.get('inbox_id') == CHATWOOT_INBOX_ID and conv.get('status') == 'open': 
                return conv.get('id')
        
        res_conv = requests.post(f"{CHATWOOT_URL}/accounts/{CHATWOOT_ACCOUNT_ID}/conversations", headers=HEADERS, json={"inbox_id": CHATWOOT_INBOX_ID, "contact_id": c_id}).json()
        return res_conv.get('id')
    except Exception as e:
        print(f"❌ Erro Chatwoot: {e}")
        return None

# ==========================================
# 2. INTELIGÊNCIA ARTIFICIAL: ÁUDIO E IMAGEM
# ==========================================
def processar_audio(media_url):
    try:
        res = requests.get(media_url, timeout=10)
        if res.status_code == 200:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".ogg")
            tmp.write(res.content)
            tmp.close()
            
            with open(tmp.name, "rb") as f:
                trans = groq_client.audio.transcriptions.create(
                    file=("audio.ogg", f.read()), 
                    model="whisper-large-v3", 
                    language="pt"
                )
            # Devolvemos um dicionário para podermos enviar o arquivo pro Chatwoot depois
            return {"texto": trans.text, "caminho": tmp.name, "tipo_arquivo": "audio/ogg", "nome": "audio.ogg"}
    except Exception as e:
        print(f"❌ Erro Áudio: {e}")
    return None

def processar_imagem(media_url):
    try:
        res = requests.get(media_url, timeout=10)
        if res.status_code == 200:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            tmp.write(res.content)
            tmp.close()
            
            with open(tmp.name, 'rb') as f:
                r = requests.post(
                    'https://api.ocr.space/parse/image', 
                    files={'file': f}, 
                    data={'apikey': OCR_API_KEY, 'language': 'por', 'OCREngine': '2', 'scale': 'true'}
                ).json()
                
                texto = r.get('ParsedResults', [{}])[0].get('ParsedText', '')
            return {"texto": texto.strip(), "caminho": tmp.name, "tipo_arquivo": "image/jpeg", "nome": "exame.jpg"}
    except Exception as e:
        print(f"❌ Erro Imagem: {e}")
    return None

# ==========================================
# 3. INTELIGÊNCIA ARTIFICIAL: CÉREBRO CONVERSACIONAL
# ==========================================
def gerar_resposta_zello(texto_paciente, fone):
    global HISTORICO_MEMORIA
    texto_limpo = str(texto_paciente).strip()
    
    if not texto_limpo:
        texto_limpo = "[Mídia sem texto detectado]"
        
    try:
        if fone not in HISTORICO_MEMORIA: 
            prompt = "Você é Zello, assistente do Hospital IBR. Aja de forma empática. Responda estritamente sobre a queixa do paciente. Faça UMA pergunta por vez."
            HISTORICO_MEMORIA[fone] = [{"role": "system", "content": prompt}]
        
        HISTORICO_MEMORIA[fone].append({"role": "user", "content": texto_limpo})
        
        if len(HISTORICO_MEMORIA[fone]) > 7:
            HISTORICO_MEMORIA[fone] = [HISTORICO_MEMORIA[fone][0]] + HISTORICO_MEMORIA[fone][-6:]

        comp = groq_client.chat.completions.create(
            messages=HISTORICO_MEMORIA[fone], 
            model="mixtral-8x7b-32768", 
            temperature=0.3,
            timeout=10.0
        )
        resposta_ia = comp.choices[0].message.content
        
        HISTORICO_MEMORIA[fone].append({"role": "assistant", "content": resposta_ia})
        return resposta_ia
        
    except Exception as e:
        print(f"❌ Erro na IA (Ativando Plano B Expandido): {e}")
        if fone in HISTORICO_MEMORIA and len(HISTORICO_MEMORIA[fone]) > 1: 
            HISTORICO_MEMORIA[fone].pop()
            
        # ==========================================
        # PLANO B EXPANDIDO: Foco no público idoso e triagem
        # ==========================================
        txt_lower = texto_limpo.lower()
        
        # 1. EMERGÊNCIA (Prioridade Máxima)
        if any(word in txt_lower for word in ["falta de ar", "peito", "coração", "desmaio", "emergência", "urgência", "sangramento"]):
            return "🤖 Zello: ALERTA: Pelo que você me disse, isso pode ser uma emergência. Por favor, venha IMEDIATAMENTE para o pronto-socorro do Hospital IBR ou ligue para o SAMU (192)."
            
        # 2. Dor e Mal-estar (Triagem)
        elif any(word in txt_lower for word in ["dor", "mal", "doendo", "febre", "ruim", "tontura", "fraco"]):
            return "🤖 Zello: Sinto muito que não esteja se sentindo bem. Onde exatamente está o incômodo e desde quando começou?"
            
        # 3. Consultas e Agendamentos
        elif any(word in txt_lower for word in ["consulta", "marcar", "agendar", "médico", "doutor"]):
            return "🤖 Zello: Claro, posso te ajudar a marcar sua consulta. Você sabe qual é a especialidade do médico que precisa (por exemplo, cardiologista, ortopedista)?"
            
        # 4. Exames e Resultados
        elif any(word in txt_lower for word in ["exame", "resultado", "raio-x", "ultrassom", "sangue"]):
            return "🤖 Zello: Certo, para marcação ou resultados de exames, um de nossos atendentes vai acessar a sua ficha agora mesmo para te ajudar. Só um instante."
            
        # 5. Receitas e Medicamentos
        elif any(word in txt_lower for word in ["receita", "remédio", "medicamento", "comprimido"]):
            return "🤖 Zello: Entendi. Se precisar renovar ou mostrar uma receita, você pode mandar a foto dela por aqui mesmo. Um atendente humano vai conferir para você."
            
        # 6. Cancelamentos
        elif any(word in txt_lower for word in ["cancelar", "desmarcar", "remarcar", "não vou poder"]):
            return "🤖 Zello: Tudo bem, imprevistos acontecem. Vou pedir para nossa equipe confirmar esse cancelamento ou reagendamento para você agorinha."
            
        # 7. Preços e Convênios
        elif any(word in txt_lower for word in ["convênio", "plano", "preço", "valor", "pagar", "unimed"]):
            return "🤖 Zello: Nós trabalhamos com diversos convênios e atendimentos particulares. Vou transferir para o setor financeiro te passar as informações certinhas. Aguarde na linha."
            
        # 8. Dificuldade ou Pedido por Humano
        elif any(word in txt_lower for word in ["atendente", "pessoa", "humano", "não sei", "difícil", "ajuda", "confuso"]):
            return "🤖 Zello: Não se preocupe, estou aqui para facilitar. Vou chamar um atendente (uma pessoa de verdade) para conversar com você e resolver tudo com calma."
            
        # 9. Cumprimentos
        elif any(word in txt_lower for word in ["oi", "olá", "bom dia", "boa tarde", "boa noite"]):
            return "🤖 Zello: Olá! Sou a Zello, a assistente virtual do Hospital IBR. Estou aqui para cuidar de você. Como posso te ajudar hoje?"
            
        # 10. Agradecimentos e Despedidas
        elif any(word in txt_lower for word in ["obrigado", "obrigada", "deus abençoe", "valeu", "tchau"]):
            return "🤖 Zello: Por nada! Fico muito feliz em ajudar. O Hospital IBR deseja muita saúde. Se precisar de mais alguma coisa, é só chamar!"
            
        # 11. Resposta Genérica (Se não cair em nada)
        else:
            return "🤖 Zello: Entendi o que você disse. Já registrei sua mensagem aqui e, para te dar a melhor resposta, um de nossos atendentes vai assumir a conversa em instantes. Por favor, aguarde só um pouquinho."

# ==========================================
# 4. WEBHOOKS PRINCIPAIS
# ==========================================
@csrf_exempt
def waha_webhook(request):
    """VIA DE IDA: WhatsApp -> Django -> Chatwoot -> Zello"""
    if request.method == 'POST':
        try:
            payload = json.loads(request.body) or {}
            data = payload.get('payload') or {}
            fone = data.get('from')
            
            # Ignora pacotes vazios
            if not fone: return JsonResponse({"status": "ignorado"}, status=200)
            
            mensagem_exibicao = data.get('body', '')
            media_info = data.get('media') or {}
            msg_tipo = (data.get('_data') or {}).get('type', '')
            dados_midia = None

            # --- PROCESSAMENTO DE MÍDIAS (Acessibilidade) ---
            if data.get('hasMedia'):
                if msg_tipo in ['ptt', 'audio', 'voice'] or 'audio' in media_info.get('mimetype', ''):
                    dados_midia = processar_audio(media_info.get('url'))
                    if dados_midia:
                        mensagem_exibicao = f"🎙️ [Áudio]: {dados_midia['texto']}"
                        
                elif msg_tipo == 'image' or 'image' in media_info.get('mimetype', ''):
                    dados_midia = processar_imagem(media_info.get('url'))
                    if dados_midia:
                        mensagem_exibicao = f"🖼️ [Imagem/Receita]: {dados_midia['texto']}"

            # --- ENVIO PARA CHATWOOT (Humano visualizar) ---
            conv_id = buscar_contato_e_conversa(fone)
            if conv_id:
                url_msg = f"{CHATWOOT_URL}/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conv_id}/messages"
                
                # Se tem arquivo (áudio ou foto), envia como anexo
                if dados_midia and dados_midia.get('caminho'):
                    with open(dados_midia['caminho'], 'rb') as f:
                        requests.post(
                            url_msg, 
                            headers={"api_access_token": CHATWOOT_API_TOKEN}, 
                            data={"content": f"*[Paciente]*: {mensagem_exibicao}", "message_type": "incoming"},
                            files=[('attachments[]', (dados_midia['nome'], f, dados_midia['tipo_arquivo']))]
                        )
                    os.remove(dados_midia['caminho']) # Apaga do servidor após o envio
                else:
                    # Mensagem de texto normal
                    requests.post(url_msg, headers=HEADERS, json={"content": f"*[Paciente]*: {mensagem_exibicao}", "message_type": "incoming"})
                
                # --- RESPOSTA DA IA ---
                # A Zello lê a mensagem (texto, transcrição ou OCR) e responde
                resposta_zello = gerar_resposta_zello(mensagem_exibicao, fone)
                requests.post(url_msg, headers=HEADERS, json={"content": resposta_zello, "message_type": "outgoing"})

            return JsonResponse({"status": "sucesso"}, status=200)
            
        except Exception as e:
            print(f"❌ Erro WAHA Webhook: {e}")
            return JsonResponse({"status": "erro_tratado"}, status=200)
            
    return JsonResponse({"erro": "Método não permitido"}, status=405)

@csrf_exempt
def chatwoot_webhook(request):
    """VIA DE VOLTA: Chatwoot -> Django -> WhatsApp"""
    if request.method == 'POST':
        try:
            payload = json.loads(request.body) or {}
            
            # Garante que só reage a mensagens enviadas (seja pelo atendente ou espelhadas pela IA)
            if payload.get('event') == 'message_created' and payload.get('message_type') == 'outgoing':
                fone = payload.get('conversation', {}).get('meta', {}).get('sender', {}).get('identifier')
                conteudo = payload.get('content', '')
                
                if fone and conteudo:
                    requests.post(f"{WAHA_URL}/api/sendText", json={"chatId": fone, "text": conteudo, "session": "default"})
                    
            return JsonResponse({"status": "sucesso"}, status=200)
        except Exception as e:
            print(f"❌ Erro Chatwoot Webhook: {e}")
            return JsonResponse({"status": "erro_tratado"}, status=200)
            
    return JsonResponse({"erro": "Método não permitido"}, status=405)