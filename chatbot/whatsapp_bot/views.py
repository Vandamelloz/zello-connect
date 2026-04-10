import json
import requests
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
load_dotenv()
# --- CHAVES DO SISTEMA ---
CHATWOOT_ACCOUNT_ID = os.getenv("CHATWOOT_ACCOUNT_ID")
CHATWOOT_API_TOKEN = os.getenv("CHATWOOT_API_TOKEN")
CHATWOOT_INBOX_ID = int(os.getenv("CHATWOOT_INBOX_ID"))
CHATWOOT_URL = "https://app.chatwoot.com/api/v1"

HEADERS = {
    "api_access_token": CHATWOOT_API_TOKEN,
    "Content-Type": "application/json"
}

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

@csrf_exempt
def waha_webhook(request):
    if request.method == 'POST':
        try:
            payload = json.loads(request.body)
            event_type = payload.get('event')
            
            if event_type in ['message', 'message.any']:
                data = payload.get('payload', {})
                mensagem_texto = data.get('body', '')
                remetente_completo = data.get('from', '')
                
                if not mensagem_texto:
                    return JsonResponse({"status": "ignorado sem texto"}, status=200)

                contact_id = buscar_ou_criar_contato(remetente_completo)
                conversation_id, conversa_nova = buscar_ou_criar_conversa(contact_id)
                
                url_msg = f"{CHATWOOT_URL}/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conversation_id}/messages"
                dados_msg = {
                    "content": f"*[Paciente]*\n{mensagem_texto}",
                    "message_type": "incoming",
                    "private": False
                }
                requests.post(url_msg, headers=HEADERS, json=dados_msg)

                if conversa_nova:
                    print(f"\n🧠 [CÉREBRO] Disparando robô para {remetente_completo}")
                    # AQUI ESTÁ A CORREÇÃO COM O NOME OFICIAL:
                    msg_robo = "🤖 *Zello Connect:* Olá! Sou o assistente virtual do hospital. Para agilizar seu atendimento, por favor, me diga seu *nome completo* e qual a sua *necessidade* hoje?"
                    
                    requests.post("http://localhost:3000/api/sendText", json={
                        "chatId": remetente_completo, 
                        "text": msg_robo,
                        "session": "default"
                    })

            return JsonResponse({"status": "recebido"}, status=200)
        except Exception as e:
            print(f"Erro na IDA: {e}")
            return JsonResponse({"erro": str(e)}, status=500)
    return JsonResponse({"erro": "Apenas POST"}, status=405)

@csrf_exempt
def chatwoot_webhook(request):
    if request.method == 'POST':
        try:
            payload = json.loads(request.body)
            evento = payload.get('event')
            tipo = payload.get('message_type')
            conteudo = payload.get('content', '')
            
            if evento == 'message_created' and tipo == 'outgoing':
                remetente_completo = payload.get('conversation', {}).get('meta', {}).get('sender', {}).get('identifier')
                
                if remetente_completo:
                    requests.post("http://localhost:3000/api/sendText", json={
                        "chatId": remetente_completo,
                        "text": conteudo,
                        "session": "default"
                    })
            return JsonResponse({"status": "recebido"}, status=200)
        except Exception as e:
            return JsonResponse({"erro": str(e)}, status=500)
    return JsonResponse({"erro": "Apenas POST"}, status=405)