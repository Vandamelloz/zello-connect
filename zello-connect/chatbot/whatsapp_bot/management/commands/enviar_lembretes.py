from django.core.management.base import BaseCommand
from django.utils import timezone
import datetime
from whatsapp_bot.models import Consulta
from whatsapp_bot.views import enviar_waha

class Command(BaseCommand):
    help = 'Envia lembretes de consulta para o dia seguinte'

    def handle(self, *args, **kwargs):
        
        amanha = timezone.now().date() + datetime.timedelta(days=1)
        
        
        self.stdout.write(f"🔍 Buscando consultas para amanhã ({amanha.strftime('%d/%m/%Y')})...")

    
        consultas = Consulta.objects.filter(
            data_hora__date=amanha, 
            status='agendada', 
            lembrete_enviado=False
        )

        total = consultas.count()

      
        if total == 0:
            self.stdout.write(self.style.WARNING("⚠️ Nenhuma consulta pendente de lembrete para amanhã."))
            return

        self.stdout.write(f"⚙️ Encontradas {total} consulta(s). Iniciando envios...")

        sucessos = 0
        for c in consultas:
            nome_paciente = c.paciente.nome if c.paciente.nome else "Paciente"
            
            mensagem = (
                f"Olá, {nome_paciente}! 🩺\n\n"
                f"Lembramos que você tem uma consulta com o(a) {c.medico.nome} "
                f"amanhã, dia {c.data_hora.strftime('%d/%m')}, às {c.data_hora.strftime('%H:%M')}.\n\n"
                "Você confirma a sua presença? Responda 1-SIM ou 2-NÃO."
            )
            
            
            sucesso = enviar_waha(c.paciente.telefone, mensagem)
            
            if sucesso:
                c.lembrete_enviado = True
                c.save() 
                self.stdout.write(self.style.SUCCESS(f"✅ Lembrete enviado para o fone: {c.paciente.telefone}"))
                sucessos += 1
            else:
                self.stdout.write(self.style.ERROR(f"❌ Falha ao tentar enviar para o fone: {c.paciente.telefone}"))

        # Resumo final
        self.stdout.write(f"🏁 Finalizado! {sucessos} de {total} lembretes enviados.")