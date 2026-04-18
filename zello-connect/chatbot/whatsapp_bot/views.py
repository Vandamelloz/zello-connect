import os
import json
import requests
import tempfile
from dotenv import load_dotenv
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from groq import Groq

load_dotenv()

CHATWOOT_ACCOUNT_ID = os.getenv("CHATWOOT_ACCOUNT_ID")
CHATWOOT_API_TOKEN = os.getenv("CHATWOOT_API_TOKEN")
CHATWOOT_INBOX_ID = int(os.getenv("CHATWOOT_INBOX_ID", 0))
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OCR_API_KEY = os.getenv("OCR_API_KEY")
WAHA_API_KEY = os.getenv("WAHA_API_KEY", "")

CHATWOOT_URL = "https://app.chatwoot.com/api/v1"
WAHA_URL = "http://localhost:3000"
HEADERS = {
    "api_access_token": CHATWOOT_API_TOKEN,
    "Content-Type": "application/json"
}

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
HISTORICO_MEMORIA = {}


MENSAGENS_PROCESSADAS = set()

def ja_processado(msg_id):
    if not msg_id:
        return False
    if msg_id in MENSAGENS_PROCESSADAS:
        return True
    MENSAGENS_PROCESSADAS.add(msg_id)
    if len(MENSAGENS_PROCESSADAS) > 500:
        MENSAGENS_PROCESSADAS.clear()
    return False
def enviar_waha(fone, texto):
    try:
        if "18343939559615" in fone or "@lid" in fone:
            chat_id = "5577981589819@c.us"
        else:
            fone_limpo = fone.split('@')[0].strip()
            if not fone_limpo or len(fone_limpo) > 15:
                print(f"⚠️ enviar_waha: fone inválido '{fone}'")
                return False
            chat_id = f"{fone_limpo}@c.us"

        headers_waha = {"Content-Type": "application/json"}
        if WAHA_API_KEY:
            headers_waha["X-Api-Key"] = WAHA_API_KEY

        resp = requests.post(
            f"{WAHA_URL}/api/sendText",
            headers=headers_waha,
            json={"chatId": chat_id, "text": texto, "session": "default"},
            timeout=10
        )
        print(f"📤 WAHA sendText ({chat_id}): HTTP {resp.status_code} | {resp.text[:100]}")
        return resp.status_code in [200, 201]
    except Exception as e:
        print(f"❌ Erro enviar_waha: {e}")
        return False

# 1. CHATWOOT

def buscar_contato_e_conversa(fone):
    fone_limpo = fone.split('@')[0].strip()

    if len(fone_limpo) > 15:
        print(f"⚠️ fone suspeito: {fone} — abortando")
        return None

    try:
        res = requests.get(
            f"{CHATWOOT_URL}/accounts/{CHATWOOT_ACCOUNT_ID}/contacts/search?q={fone_limpo}",
            headers=HEADERS
        ).json()
        payload_busca = res.get('payload') or []

        if payload_busca:
            c_id = payload_busca[0].get('id')
        else:
            res_cria = requests.post(
                f"{CHATWOOT_URL}/accounts/{CHATWOOT_ACCOUNT_ID}/contacts",
                headers=HEADERS,
                json={
                    "name": f"Paciente {fone_limpo[:8]}",
                    "identifier": fone_limpo,
                    "phone_number": f"+{fone_limpo}"
                }
            ).json()
            c_id = res_cria.get('payload', {}).get('contact', {}).get('id')

        res_c = requests.get(
            f"{CHATWOOT_URL}/accounts/{CHATWOOT_ACCOUNT_ID}/contacts/{c_id}/conversations",
            headers=HEADERS
        ).json()
        lista_conversas = res_c.get('payload') or []
        for conv in lista_conversas:
            if conv.get('inbox_id') == CHATWOOT_INBOX_ID and conv.get('status') == 'open':
                return conv.get('id')

        res_conv = requests.post(
            f"{CHATWOOT_URL}/accounts/{CHATWOOT_ACCOUNT_ID}/conversations",
            headers=HEADERS,
            json={"inbox_id": CHATWOOT_INBOX_ID, "contact_id": c_id}
        ).json()
        return res_conv.get('id')

    except Exception as e:
        print(f"❌ Erro Chatwoot: {e}")
        return None


# 2. MÍDIA- Onde ocorre o processo de acessibilidade audiovisual

def extrair_info_midia(data):
    media = data.get('media') or {}
    url = media.get('url') or data.get('mediaUrl') or data.get('fileUrl') or ''
    mimetype = (
        media.get('mimetype')
        or media.get('mimeType')
        or data.get('mimetype')
        or ''
    ).lower()
    msg_type = (
        data.get('type')
        or (data.get('_data') or {}).get('type')
        or ''
    ).lower()
    return url, mimetype, msg_type


def processar_audio(media_url):
    try:
        headers_waha = {}
        if WAHA_API_KEY:
            headers_waha["X-Api-Key"] = WAHA_API_KEY

        res = requests.get(media_url, headers=headers_waha, timeout=15)
        print(f"🔊 Download áudio: status={res.status_code}, bytes={len(res.content)}")

        if res.status_code == 200 and len(res.content) > 100:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".ogg")
            tmp.write(res.content)
            tmp.close()
            with open(tmp.name, "rb") as f:
                trans = groq_client.audio.transcriptions.create(
                    file=("audio.ogg", f.read()),
                    model="whisper-large-v3",
                    language="pt"
                )
            print(f"✅ Áudio transcrito: {trans.text[:80]}")
            return {
                "texto": trans.text,
                "caminho": tmp.name,
                "tipo_arquivo": "audio/ogg",
                "nome": "audio.ogg"
            }
        else:
            print(f"❌ Falha download áudio: {res.status_code} — {res.text[:200]}")

    except Exception as e:
        print(f"❌ Erro Áudio: {e}")
    return None


def processar_imagem(media_url):
    try:
        headers_waha = {}
        if WAHA_API_KEY:
            headers_waha["X-Api-Key"] = WAHA_API_KEY

        res = requests.get(media_url, headers=headers_waha, timeout=15)
        print(f"🖼️ Download imagem: status={res.status_code}, bytes={len(res.content)}")

        if res.status_code == 200 and len(res.content) > 100:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            tmp.write(res.content)
            tmp.close()
            with open(tmp.name, 'rb') as f:
                r = requests.post(
                    'https://api.ocr.space/parse/image',
                    files={'file': f},
                    data={
                        'apikey': OCR_API_KEY,
                        'language': 'por',
                        'OCREngine': '2',
                        'scale': 'true'
                    }
                ).json()
            texto = r.get('ParsedResults', [{}])[0].get('ParsedText', '')
            return {
                "texto": texto.strip(),
                "caminho": tmp.name,
                "tipo_arquivo": "image/jpeg",
                "nome": "exame.jpg"
            }
        else:
            print(f"❌ Falha download imagem: {res.status_code}")

    except Exception as e:
        print(f"❌ Erro Imagem: {e}")
    return None

# 3. IA — Zello

def gerar_resposta_zello(texto_paciente, fone):
    global HISTORICO_MEMORIA
    texto_limpo = str(texto_paciente).strip() or "[Mídia sem texto detectado]"

    try:
        if fone not in HISTORICO_MEMORIA:
            prompt = (
                "Você é Zello, assistente virtual do Hospital IBR. "
                "Aja de forma empática e acolhedora. "
                "Responda somente sobre assuntos relacionados ao atendimento hospitalar. "
                "Faça UMA pergunta por vez."
            )
            HISTORICO_MEMORIA[fone] = [{"role": "system", "content": prompt}]

        HISTORICO_MEMORIA[fone].append({"role": "user", "content": texto_limpo})

        if len(HISTORICO_MEMORIA[fone]) > 7:
            HISTORICO_MEMORIA[fone] = [HISTORICO_MEMORIA[fone][0]] + HISTORICO_MEMORIA[fone][-6:]

        comp = groq_client.chat.completions.create(
            messages=HISTORICO_MEMORIA[fone],
            model="llama-3.3-70b-versatile",
            temperature=0.3,
            timeout=10.0
        )
        resposta_ia = comp.choices[0].message.content
        HISTORICO_MEMORIA[fone].append({"role": "assistant", "content": resposta_ia})
        return resposta_ia

    except Exception as e:
        print(f"❌ Erro na IA (Plano B): {e}")
        if fone in HISTORICO_MEMORIA and len(HISTORICO_MEMORIA[fone]) > 1:
            HISTORICO_MEMORIA[fone].pop()

    # --- PLANO B ---
    txt_lower = texto_limpo.lower()
    if any(w in txt_lower for w in ["falta de ar", "peito", "coração", "desmaio", "emergência", "urgência", "sangramento"]):
        return "Zello (IBR): ALERTA: Pelo que você me disse, isso pode ser uma emergência. Por favor, venha IMEDIATAMENTE para o pronto-socorro do Hospital IBR ou ligue para o SAMU (192)."
    elif any(w in txt_lower for w in ["dor", "mal", "doendo", "febre", "ruim", "tontura", "fraco"]):
        return "Zello (IBR): Sinto muito que não esteja se sentindo bem. Onde exatamente está o incômodo e desde quando começou?"
    elif any(w in txt_lower for w in ["consulta", "marcar", "agendar", "médico", "doutor"]):
        return "Zello (IBR): Claro, posso te ajudar a marcar sua consulta. Você sabe qual especialidade precisa (ex: cardiologista, ortopedista)?"
    elif any(w in txt_lower for w in ["exame", "resultado", "raio-x", "ultrassom", "sangue"]):
        return "Zello (IBR): Certo, um atendente vai acessar sua ficha agora mesmo. Só um instante."
    elif any(w in txt_lower for w in ["receita", "remédio", "medicamento", "comprimido"]):
        return "Zello (IBR): Pode mandar a foto da receita por aqui. Um atendente vai conferir para você."
    elif any(w in txt_lower for w in ["cancelar", "desmarcar", "remarcar"]):
        return "Zello (IBR): Tudo bem, vou pedir para a equipe confirmar esse reagendamento agora."
    elif any(w in txt_lower for w in ["convênio", "plano", "preço", "valor", "pagar"]):
        return "Zello (IBR): Vou transferir para o setor financeiro te passar as informações. Aguarde."
    elif any(w in txt_lower for w in ["atendente", "pessoa", "humano", "ajuda"]):
        return "Zello (IBR): Vou chamar um atendente para conversar com você agora mesmo."
    elif any(w in txt_lower for w in ["oi", "olá", "bom dia", "boa tarde", "boa noite"]):
        return "Zello (IBR): Olá! Sou a Zello, assistente do Hospital IBR. Como posso te ajudar hoje?"
    elif any(w in txt_lower for w in ["obrigado", "obrigada", "valeu", "tchau"]):
        return "Zello (IBR): Por nada! O Hospital IBR deseja muita saúde. Se precisar, é só chamar!"
    else:
        return "Zello (IBR): Recebi sua mensagem. Um atendente vai assumir a conversa em instantes. Por favor, aguarde."

# 4. WEBHOOK — WAHA → Django → Chatwoot + Zello

@csrf_exempt
def waha_webhook(request):
    if request.method != 'POST':
        return JsonResponse({"erro": "Método não permitido"}, status=405)

    try:
        payload = json.loads(request.body) or {}

      
        print(f"🔍 PAYLOAD from={payload.get('payload', {}).get('from')} | keys={list(payload.keys())} | payload_keys={list((payload.get('payload') or {}).keys())}")

        data = payload.get('payload') or {}

        msg_id = data.get('id') or payload.get('id')
        if ja_processado(msg_id):
            return JsonResponse({"status": "duplicado_ignorado"}, status=200)

        fone = data.get('from', '')
        print(f"🔍 fone bruto recebido: '{fone}'")

        # Ignora grupos, broadcasts e mensagens próprias
        if not fone or "@g.us" in fone or "@broadcast" in fone:
            return JsonResponse({"status": "ignorado"}, status=200)

        if data.get('fromMe') or (data.get('_data') or {}).get('fromMe'):
            return JsonResponse({"status": "ignorado_proprio"}, status=200)

        mensagem_exibicao = data.get('body', '')
        dados_midia = None

        # Detecção de mídia
        if data.get('hasMedia'):
            url_midia, mimetype, msg_type = extrair_info_midia(data)
            print(f"🎯 Mídia: type={msg_type}, mime={mimetype}, url={url_midia[:80] if url_midia else 'VAZIA'}")

            eh_audio = (
                msg_type in ['ptt', 'audio', 'voice']
                or 'audio' in mimetype
                or 'ogg' in mimetype
            )
            eh_imagem = (
                msg_type == 'image'
                or 'image' in mimetype
            )

            if eh_audio and url_midia:
                dados_midia = processar_audio(url_midia)
                if dados_midia:
                    mensagem_exibicao = f"🎙️ [Áudio transcrito]: {dados_midia['texto']}"
                else:
                    mensagem_exibicao = "🎙️ [Áudio recebido — transcrição indisponível]"

            elif eh_imagem and url_midia:
                dados_midia = processar_imagem(url_midia)
                if dados_midia:
                    mensagem_exibicao = f"🖼️ [Imagem/Receita]: {dados_midia['texto']}"
                else:
                    mensagem_exibicao = "🖼️ [Imagem recebida — OCR indisponível]"

        # Registra no Chatwoot
        conv_id = buscar_contato_e_conversa(fone)
        if conv_id:
            url_msg = f"{CHATWOOT_URL}/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conv_id}/messages"

            if dados_midia and dados_midia.get('caminho'):
                with open(dados_midia['caminho'], 'rb') as f:
                    requests.post(
                        url_msg,
                        headers={"api_access_token": CHATWOOT_API_TOKEN},
                        data={
                            "content": f"*[Paciente]*: {mensagem_exibicao}",
                            "message_type": "incoming"
                        },
                        files=[('attachments[]', (dados_midia['nome'], f, dados_midia['tipo_arquivo']))]
                    )
                os.remove(dados_midia['caminho'])
            else:
                requests.post(
                    url_msg,
                    headers=HEADERS,
                    json={
                        "content": f"*[Paciente]*: {mensagem_exibicao}",
                        "message_type": "incoming"
                    }
                )

      
            resposta_zello_pura = gerar_resposta_zello(mensagem_exibicao, fone)
            
          
            if resposta_zello_pura.startswith("Zello (IBR):"):
                resposta_com_emoji = resposta_zello_pura.replace("Zello (IBR):", "🩺 Zello:")
            else:
                resposta_com_emoji = f"🩺 {resposta_zello_pura}"

            requests.post(
                url_msg,
                headers=HEADERS,
                json={"content": f"*[Zello]* {resposta_com_emoji}", "message_type": "outgoing"}
            )

          
            print(f"🤖 Zello vai responder para fone='{fone}'")
            enviar_waha(fone, resposta_com_emoji)

        return JsonResponse({"status": "sucesso"}, status=200)

    except Exception as e:
        print(f"❌ Erro WAHA Webhook: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({"status": "erro_tratado"}, status=200)



# 5. WEBHOOK — Chatwoot → Django → WAHA

@csrf_exempt
def chatwoot_webhook(request):
    if request.method != 'POST':
        return JsonResponse({"erro": "Método não permitido"}, status=405)

    try:
        payload = json.loads(request.body) or {}

        event = payload.get('event')
        msg_type = payload.get('message_type')
        remetente = payload.get('sender') or {}
        tipo_conta = remetente.get('type', '')
        conteudo = payload.get('content', '') or ''

        if event == 'message_created' and msg_type == 'outgoing':

       
            if tipo_conta == 'agent_bot':
                return JsonResponse({"status": "ignorado_bot"}, status=200)

          
            if conteudo.startswith('*[Paciente]*') or conteudo.startswith('*[Zello]*'):
                return JsonResponse({"status": "ignorado_espelho"}, status=200)

         
            remetente_email = remetente.get('email', '')
            if not remetente_email:
                return JsonResponse({"status": "ignorado_sem_email"}, status=200)

            fone_raw = (
                payload.get('conversation', {})
                .get('meta', {})
                .get('sender', {})
                .get('identifier', '')
            )
            fone_limpo = fone_raw.split('@')[0].strip() if fone_raw else ''

            print(f"👤 Humano ({remetente_email}) → WhatsApp: fone={fone_limpo}, msg={conteudo[:60]}")

            if fone_limpo and conteudo and len(fone_limpo) <= 15:
                enviar_waha(fone_limpo, conteudo)
            elif len(fone_limpo) > 15:
                print(f"⚠️ fone longo demais (possível @lid): {fone_raw}")
            else:
                print(f"⚠️ fone ou conteúdo vazio")

        return JsonResponse({"status": "sucesso"}, status=200)

    except Exception as e:
        print(f"❌ Erro Chatwoot Webhook: {e}")
        return JsonResponse({"status": "erro_tratado"}, status=200)