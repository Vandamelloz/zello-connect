from django.db import models

# 1. Tabela de Pacientes
class Paciente(models.Model):
    nome = models.CharField(max_length=255, blank=True, null=True)
    # O telefone é a nossa chave principal para conectar com o WhatsApp (ex: 5577981589819)
    telefone = models.CharField(max_length=20, unique=True) 
    cpf = models.CharField(max_length=14, blank=True, null=True)
    data_cadastro = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nome or 'Paciente Sem Nome'} ({self.telefone})"

# 2. Tabela de Médicos
class Medico(models.Model):
    nome = models.CharField(max_length=255)
    especialidade = models.CharField(max_length=100) # Ex: Cardiologia, Ortopedia
    ativo = models.BooleanField(default=True)

    def __str__(self):
        return f"Dr(a). {self.nome} - {self.especialidade}"

# 3. Tabela de Consultas (Onde a mágica do agendamento acontece)
class Consulta(models.Model):
    STATUS_CHOICES = [
        ('agendada', 'Agendada'),
        ('cancelada', 'Cancelada'),
        ('realizada', 'Realizada'),
    ]

    paciente = models.ForeignKey(Paciente, on_delete=models.CASCADE, related_name='consultas')
    medico = models.ForeignKey(Medico, on_delete=models.CASCADE, related_name='consultas')
    data_hora = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='agendada')
    criado_em = models.DateTimeField(auto_now_add=True)
    confirmada = models.BooleanField(default=False) 
    lembrete_enviado = models.BooleanField(default=False) 

    convenio = models.CharField(max_length=100, default='Particular', blank=True, null=True) 
    
    criado_em = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f"{self.paciente.nome} com {self.medico.nome} em {self.data_hora.strftime('%d/%m/%Y %H:%M')}"
