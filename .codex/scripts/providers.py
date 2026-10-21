"""Adaptadores REST sem SDK, ferramentas remotas, upload de PDF ou chave em disco.

Contrato: a aplicação autenticada injeta a chave apenas no worker do usuário.
Não executar chamadas reais durante testes desta skill.
"""
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass


class ProviderError(RuntimeError):
    """Mensagem sanitizada; nunca propagar corpo HTTP, headers ou a exceção original."""


def provider_name(value):
    value = str(value).strip().lower()
    value = {'chatgpt': 'openai', 'claude': 'anthropic'}.get(value, value)
    if value not in {'openai', 'anthropic', 'gemini'}:
        raise ValueError('Provedor deve ser Gemini, Claude ou ChatGPT/OpenAI.')
    return value


@dataclass(frozen=True)
class Reply:
    text: str
    input_tokens: int
    output_tokens: int
    complete: bool


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def post_json(url, headers, payload):
    """Endpoints fixos; sem redirecionar a chave. Sem retries ocultos."""
    request = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'),
                                     headers={**headers, 'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=45) as response:
            body = response.read(8_000_001)
            if len(body) > 8_000_000:
                raise ProviderError('RESPOSTA_EXCESSIVA')
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        # A fila decide quando retomar; não imprimir exc, request ou resposta HTTP.
        code = exc.code
        raise ProviderError(f'HTTP_{code}') from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ProviderError('CONEXAO_INDETERMINADA') from None
    except (ValueError, TypeError):
        raise ProviderError('RESPOSTA_HTTP_INVALIDA') from None


def integer(value):
    if type(value) is not int or value < 0:
        raise ProviderError('USO_DE_TOKENS_AUSENTE_OU_INVALIDO')
    return value


class Provider:
    def __init__(self, name, model, *, transport=post_json):
        self.name = provider_name(name)
        if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,150}', model):
            raise ValueError('ID do modelo inválido. Não aceitar URL ou caminho.')
        self.model, self.transport = model, transport

    def request(self, *, api_key, system, prompt, schema, max_output):
        if not isinstance(api_key, str) or not api_key.strip() or any(c in api_key for c in '\r\n'):
            raise ProviderError('CHAVE_AUSENTE_OU_INVALIDA')
        if self.name == 'openai':
            url = 'https://api.openai.com/v1/responses'
            headers = {'Authorization': 'Bearer ' + api_key}
            payload = {'model': self.model, 'store': False, 'instructions': system,
                       'input': prompt, 'max_output_tokens': max_output,
                       'text': {'format': {'type': 'json_schema', 'name': 'supervisao_shr',
                                           'strict': True, 'schema': schema}}}
        elif self.name == 'anthropic':
            url = 'https://api.anthropic.com/v1/messages'
            headers = {'x-api-key': api_key, 'anthropic-version': '2023-06-01'}
            payload = {'model': self.model, 'system': system, 'max_tokens': max_output,
                       'messages': [{'role': 'user', 'content': prompt}],
                       'output_config': {'format': {'type': 'json_schema', 'schema': schema}}}
        else:
            url = f'https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent'
            headers = {'x-goog-api-key': api_key}
            payload = {'systemInstruction': {'parts': [{'text': system}]},
                       'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
                       'generationConfig': {'maxOutputTokens': max_output,
                                            # generateContent uses responseMimeType/responseSchema.
                                            # responseFormat belongs to the separate Interactions API.
                                            'responseMimeType': 'application/json',
                                            'responseSchema': schema}}
        try:
            raw = self.transport(url, headers, payload)
        except ProviderError:
            raise
        except Exception:
            raise ProviderError('FALHA_TRANSPORTE') from None
        try:
            if self.name == 'openai':
                blocks = [b for item in raw.get('output', []) if item.get('type') == 'message'
                          for b in item.get('content', [])]
                complete = raw.get('status') == 'completed' and not any(b.get('type') == 'refusal' for b in blocks)
                text = ''.join(b['text'] for b in blocks if b.get('type') == 'output_text')
                usage = raw['usage']
                input_tokens, output_tokens = integer(usage['input_tokens']), integer(usage['output_tokens'])
            elif self.name == 'anthropic':
                text = ''.join(b['text'] for b in raw.get('content', []) if b.get('type') == 'text')
                complete = raw.get('stop_reason') == 'end_turn'
                usage = raw['usage']
                input_tokens = sum(integer(usage.get(k, 0)) for k in
                                   ['input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'])
                output_tokens = integer(usage['output_tokens'])
                if 'input_tokens' not in usage:
                    raise ProviderError('USO_DE_TOKENS_AUSENTE_OU_INVALIDO')
            else:
                candidates = raw.get('candidates', [])
                candidate = candidates[0] if len(candidates) == 1 else {}
                text = ''.join(p['text'] for p in candidate.get('content', {}).get('parts', [])
                               if 'text' in p and not p.get('thought'))
                complete = candidate.get('finishReason') == 'STOP'
                usage = raw['usageMetadata']
                input_tokens = integer(usage['promptTokenCount'])
                # Inclui raciocínio quando o provedor o informa separadamente.
                output_tokens = integer(usage['candidatesTokenCount']) + integer(usage.get('thoughtsTokenCount', 0))
            return Reply(text, input_tokens, output_tokens, complete and bool(text))
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ProviderError('RESPOSTA_DO_PROVEDOR_INVALIDA') from None
