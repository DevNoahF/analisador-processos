# APIs dos provedores

Conferência documental em 21/10/2026. Não fixar nomes de modelos nem preços na skill.
O site deve oferecer IDs de modelos disponíveis na conta, com saída JSON estruturada
e limites apropriados, configurados pelo administrador.

| Opção no site | Adaptador | Interface REST |
|---|---|---|
| ChatGPT / OpenAI API | `openai` (alias `chatgpt`) | Responses `/v1/responses`, `text.format` JSON Schema estrito, `store: false` |
| Claude | `anthropic` (alias `claude`) | Messages `/v1/messages`, `output_config.format` JSON Schema |
| Gemini | `gemini` | Generate Content `/v1beta/models/{id}:generateContent`, `generationConfig.responseFormat.text.schema` |

O adaptador Gemini usa a interface Generate Content documentada como Legacy nesta
data. Não misturar seus campos com a Interactions API. Reavaliar migração antes de
produção se o modelo escolhido exigir a API nova. Não mandar a chave na query string.

Usar JSON Schema simples e validar novamente no servidor: estrutura, enum, cobertura
de segmentos e citações exatas. Uma resposta truncada/recusada não vale como revisão.
O adaptador não usa temperatura, ferramentas, grounding ou busca remota. Modelos com
parâmetros obrigatórios extras exigem adaptação e teste; não escolher um silenciosamente.

Fontes oficiais para verificar alterações de contrato:

- [OpenAI: Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [OpenAI: Responses e armazenamento](https://developers.openai.com/api/docs/guides/migrate-to-responses)
- [Claude: Structured Outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- [Claude: Messages](https://platform.claude.com/docs/en/api/messages/create)
- [Claude: contagem de tokens](https://platform.claude.com/docs/en/build-with-claude/token-counting)
- [Gemini: JSON em Generate Content](https://ai.google.dev/gemini-api/docs/generate-content/structured-output)
- [Gemini: contagem de tokens](https://ai.google.dev/gemini-api/docs/tokens)

`store:false` é um parâmetro da OpenAI, não uma promessa universal de retenção zero
dos três provedores. O site informa o provedor escolhido e usa suas condições vigentes.
Relatórios de uso e custo são por job e usuário, sem registrar credenciais.
