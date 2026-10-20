# Testes

## Executar

```bash
uv sync --extra dev
uv run python -m pytest -q
```

Os testes JavaScript usam o runner nativo do **Node.js 20 ou superior**, sem pacotes npm.
Cada cenário é exposto pelo pytest, portanto o comando acima executa Python e JavaScript.
Quando o Node está ausente ou é anterior à versão 20, esses cenários aparecem como ignorados, com o motivo.

Para executar somente as regressões de integridade:

```bash
uv run python -m pytest -q \
  tests/test_upload_integrity.py \
  tests/test_scout_usage.py \
  tests/test_integrity_interfaces.py \
  tests/test_studio_javascript.py
```

Para executar somente o JavaScript:

```bash
node --test tests/js/studio_integrity.test.cjs
```

## Cobertura das regressões de integridade

| Arquivo | Cenários |
| --- | --- |
| `test_upload_integrity.py` | Reservas persistentes, concorrência entre instâncias, cota e horários exclusivos, tokens inválidos ou antigos, rollback, reinício, processo interrompido, resposta incerta, reconciliação manual, autorização, falhas de limpeza, descrição inválida e mudanças de horário do Pacífico. |
| `test_scout_usage.py` | Registro do Scout, consumo, zero e desconhecido, valores mínimos, rateio entre produtos/vídeos/traduções, falhas parciais, reaproveitamento, concorrência, reconciliação de estimativas, orçamentos, persistência e falhas da telemetria. |
| `test_integrity_interfaces.py` | Agenda inválida ou cheia, limite da descrição em bytes UTF-8, links completos, API autenticada e entradas ambíguas, preservação da ideia após falha, identidade do roteiro, CLI e mensagens MCP. |
| `js/studio_integrity.test.cjs` | Persistência atômica de rascunho e origem, recuperação de versões, erros de HTTP/worker/storage, isolamento de sessões, cliques duplicados, salvamento ordenado de afiliados, recuperação dos campos após reload e controles de reconciliação. |

As novas regressões usam SQLite temporário, sockets HTTP em memória, provedores simulados e ambiente JavaScript
isolado com DOM e armazenamento simulados. Não há publicação, OAuth, chamadas pagas ou renderização nesses arquivos.
O JavaScript carrega os arquivos reais `app.js` e `costs.js`, preservando o código das funções exercitadas.

A suíte completa também contém testes de integração local com HTTP em `127.0.0.1` e renderização offline com FFmpeg.
Ambientes que bloqueiam portas locais precisam permitir esses servidores de teste. O suporte a ASS depende do
FFmpeg disponível; o teste informa quando esse caminho não pode ser executado.

## Limites

Testes JavaScript isolados verificam lógica, estado, markup e callbacks; não verificam layout, contraste,
comportamento completo do navegador ou experiência com leitor de tela. Integrações reais com provedores e
YouTube continuam exigindo validação separada. O ciclo completo de abandono e retomada de ideias ainda está
pendente de implementação; os testes atuais cobrem a devolução da ideia nos caminhos de falha corrigidos.
