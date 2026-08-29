# Guia de Instalação do Agente Nimbus

## Requisitos

Roda em Linux (kernel 4.14+), macOS 12+ e Windows Server 2019+.
Requer 256 MB de RAM livre e 1 GB de disco para o buffer local.

## Instalação

Em distribuições baseadas em Debian:

    curl -fsSL https://get.nimbus.example/install.sh | sh
    sudo systemctl enable --now nimbus-agent

O instalador cria a configuração em /etc/nimbus/agent.yaml.

## Configuração mínima

O agente precisa do token de ingestão e da região.

    api_key: nmb_xxxxxxxxxxxx
    region: sa-east-1
    buffer_size_mb: 512

Se o buffer encher porque a rede caiu, o agente descarta os eventos mais
antigos primeiro. Aumente buffer_size_mb em ambientes instáveis.

## Problemas comuns

O erro "certificate verify failed" quase sempre indica relógio do sistema
fora de sincronia. Sincronize com NTP antes de investigar outra coisa.

Se `nimbus-agent status` mostrar "unauthorized", o token está incorreto
ou foi revogado.
