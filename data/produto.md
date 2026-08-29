# Nimbus — Documentação do Produto

## O que é o Nimbus

Nimbus é uma plataforma de observabilidade para aplicações distribuídas.
Coleta métricas, logs e traces de serviços em produção e os correlaciona
em uma única linha do tempo.

## Planos e preços

- **Starter**: R$ 290 por mês. 50 GB de ingestão de logs, retenção de
  7 dias, até 5 usuários. Não inclui alertas por telefone.
- **Growth**: R$ 890 por mês. 300 GB de ingestão, retenção de 30 dias,
  usuários ilimitados, alertas por telefone e SMS.
- **Enterprise**: sob consulta. Retenção de 13 meses, VPC dedicada,
  SLA de 99,95% e gerente de conta designado.

Ingestão excedente custa R$ 3,20 por GB adicional em todos os planos.

## Como cancelar a assinatura

Para encerrar seu plano, acesse Configurações > Faturamento e clique em
"Encerrar plano". O cancelamento vale a partir do fim do ciclo já pago —
não há reembolso proporcional. Seus dados ficam disponíveis para exportação
por 30 dias após o encerramento; depois são apagados definitivamente.

Contas Enterprise exigem aviso prévio de 60 dias, conforme contrato.

## Limites técnicos

- Tamanho máximo de um evento de log: 256 KB.
- Taxa máxima de ingestão por token: 10.000 eventos por segundo.
- Retenção máxima de traces: 15 dias, independente do plano.
- Cardinalidade máxima de labels por métrica: 50.000 séries distintas.

Ultrapassar a taxa gera HTTP 429 e os eventos excedentes são descartados —
não há fila de retentativa no servidor.
