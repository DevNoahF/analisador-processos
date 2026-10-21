"""Testes offline: sem rede, sem chaves reais e sem PDFs de clientes no pacote."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plan_workbook import plan_write
from providers import Provider, ProviderError, Reply, provider_name
from supervisao import Limits, Supervisor, prepare
from test_decidir_lote import complete, PROCESS

SECRET = 'chave-ficticia-somente-para-testes'
SHA = 'a' * 64


def inventory(*, bad_reading=False, length=150):
    return {'sha256': SHA, 'file_name': 'processo-ficticio.pdf', 'page_count': 2,
            'primary_process': PROCESS, 'alerts': [], 'pages': [
                {'pdf_page': 1, 'text': 'Capa oficial e identificação do processo. ' * length, 'flags': []},
                {'pdf_page': 2, 'text': 'Substabelecimento destinado à SHR e protocolo da peça. ' * length,
                 'flags': ['OCR_OU_CONFERENCIA_DO_CORPO'] if bad_reading else []}]}


def record():
    r = complete()
    r.update(record_id='registro-estavel-1', source_ids=[SHA])
    return r


def result_for(prompt):
    data = json.loads(prompt)
    return {'reviewed_segments': [s['id'] for s in data['segments']], 'verdict': 'SEM_DIVERGENCIA',
            'facts': [], 'findings': []}


class FakeProvider:
    name, model = 'gemini', 'modelo-ficticio'

    def __init__(self, mutate=None, fail=None):
        self.requests, self.mutate, self.fail = [], mutate, fail

    def request(self, *, api_key, system, prompt, schema, max_output):
        self.requests.append(prompt)
        if self.fail:
            raise ProviderError(self.fail)
        data = result_for(prompt)
        if self.mutate:
            self.mutate(data, json.loads(prompt))
        return Reply(json.dumps(data), 60, 60, True)


class Providers(unittest.TestCase):
    def test_labels_and_fixed_endpoint(self):
        self.assertEqual(provider_name('ChatGPT'), 'openai')
        self.assertEqual(provider_name('Claude'), 'anthropic')
        with self.assertRaises(ValueError):
            Provider('gemini', '../chave?api_key=teste')

    def test_three_rest_formats_and_usage(self):
        def transport(url, headers, payload):
            self.assertNotIn(SECRET, url)
            self.assertNotIn(SECRET, json.dumps(payload))
            if '/responses' in url:
                self.assertEqual(headers['Authorization'], 'Bearer ' + SECRET)
                self.assertIs(payload['store'], False)
                self.assertTrue(payload['text']['format']['strict'])
                return {'status': 'completed', 'output': [{'type': 'message', 'content': [
                    {'type': 'output_text', 'text': '{}'}]}], 'usage': {'input_tokens': 11, 'output_tokens': 12}}
            if 'anthropic' in url:
                self.assertEqual(headers['x-api-key'], SECRET)
                self.assertEqual(payload['output_config']['format']['type'], 'json_schema')
                return {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': '{}'}],
                        'usage': {'input_tokens': 4, 'cache_read_input_tokens': 7, 'output_tokens': 12}}
            self.assertEqual(headers['x-goog-api-key'], SECRET)
            self.assertEqual(payload['generationConfig']['responseMimeType'], 'application/json')
            self.assertEqual(payload['generationConfig']['responseSchema'], {'type': 'object'})
            self.assertNotIn('responseFormat', payload['generationConfig'])
            return {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': '{}'}]}}],
                    'usageMetadata': {'promptTokenCount': 11, 'candidatesTokenCount': 10, 'thoughtsTokenCount': 2}}
        for name in ['openai', 'anthropic', 'gemini']:
            reply = Provider(name, 'modelo-ficticio', transport=transport).request(
                api_key=SECRET, system='sistema', prompt='dados', schema={'type': 'object'}, max_output=50)
            self.assertEqual((reply.input_tokens, reply.output_tokens, reply.complete), (11, 12, True))

    def test_transport_error_does_not_leak_secret(self):
        def broken(*args):
            raise RuntimeError(SECRET)
        with self.assertRaises(ProviderError) as error:
            Provider('openai', 'teste', transport=broken).request(
                api_key=SECRET, system='s', prompt='p', schema={}, max_output=50)
        self.assertNotIn(SECRET, str(error.exception))


class Workflow(unittest.TestCase):
    def run_it(self, *, files=None, records=None, limits=Limits(), provider=None, checkpoint=None):
        plan = prepare(files or [inventory()], [record()] if records is None else records, limits)
        runner = Supervisor(owner_id='usuario-1', job_id='lote-1', provider=provider or FakeProvider(),
                            limits=limits, checkpoint=checkpoint)
        return runner, plan, runner.run(plan, api_key=SECRET)

    def test_all_text_and_cross_review(self):
        provider = FakeProvider()
        _, plan, out = self.run_it(provider=provider)
        self.assertEqual(out['status'], 'REVISAO_CONCLUIDA')
        sent = [s['text'] for p in provider.requests for s in json.loads(p)['segments']
                if json.loads(p)['stage'] == 'paginas']
        self.assertEqual(''.join(sent), ''.join(p['text'] for p in inventory()['pages']))
        self.assertEqual(out['records'][0]['amount_brl'], 450)
        self.assertEqual(out['records'][0]['status'], 'APTO À CONFERÊNCIA FINAL')

    def test_resume_uses_cache_and_no_secret_in_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'privado.json'
            provider = FakeProvider()
            runner, plan, out = self.run_it(provider=provider, checkpoint=path)
            calls = len(provider.requests)
            resumed = Supervisor(owner_id='usuario-1', job_id='lote-1', provider=provider, checkpoint=path)
            self.assertEqual(resumed.run(plan, api_key=SECRET)['calls'], out['calls'])
            self.assertEqual(len(provider.requests), calls)
            self.assertNotIn(SECRET, path.read_text())
            with self.assertRaises(ValueError):
                Supervisor(owner_id='outro-usuario', job_id='lote-1', provider=provider, checkpoint=path)

    def test_budget_stops_without_approval(self):
        _, _, out = self.run_it(limits=Limits(max_calls=1))
        self.assertEqual(out['records'][0]['status'], 'PENDENTE')
        self.assertEqual(out['calls'], 1)
        self.assertEqual(out['status'], 'PENDENTE')

    def test_budget_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'privado.json'
            provider = FakeProvider()
            _, plan, first = self.run_it(limits=Limits(max_calls=1), provider=provider, checkpoint=path)
            runner = Supervisor(owner_id='usuario-1', job_id='lote-1', provider=provider, checkpoint=path)
            out = runner.run(plan, api_key=SECRET)
            self.assertEqual(first['calls'], 1)
            self.assertEqual(out['status'], 'REVISAO_CONCLUIDA')
            self.assertEqual(len(provider.requests), out['calls'])

    def test_bad_citation_and_coverage_block(self):
        def cite(data, prompt):
            s = prompt['segments'][0]
            data['facts'] = [{'field': 'subs', 'value': '2025-04-02', 'evidence': [
                {'source_id': s['source_id'], 'page': s['page'], 'quote': 'Citação que não existe no PDF'}]}]
        for mutate in [cite, lambda d, p: d.update(reviewed_segments=[]),
                       lambda d, p: d.update(campo_extra='tentativa')]:
            _, _, out = self.run_it(provider=FakeProvider(mutate=mutate))
            self.assertEqual(out['status'], 'PENDENTE')
            self.assertEqual(out['errors'][0]['code'], 'JSON_OU_CITACAO_INVALIDA')

    def test_ocr_is_not_cleared_by_ai(self):
        _, _, out = self.run_it(files=[inventory(bad_reading=True)])
        self.assertTrue(out['coverage'][0]['text_review_complete'])
        self.assertFalse(out['coverage'][0]['reading_complete'])
        self.assertEqual(out['records'][0]['status'], 'PENDENTE')

    def test_duplicate_pdf_not_duplicate_process(self):
        first = inventory()
        second = deepcopy(first)
        second['sha256'] = 'b' * 64
        plan = prepare([first, first, second], [record()])
        self.assertEqual(len(plan['documents']), 2)
        self.assertEqual(len(plan['duplicates']), 1)

    def test_no_record_pdf_still_reviewed_and_flagged(self):
        provider = FakeProvider()
        _, _, out = self.run_it(records=[], provider=provider)
        self.assertTrue(out['coverage'][0]['text_review_complete'])
        self.assertTrue(any(json.loads(p)['stage'] == 'cruzada' for p in provider.requests))
        self.assertEqual(out['status'], 'PENDENTE')

    def test_changed_rules_invalidate_plan(self):
        runner, plan, _ = self.run_it()
        plan['rules']['contracts'] += '\nRegra diferente.'
        with self.assertRaises(ValueError):
            runner.run(plan, api_key=SECRET)

    def test_changed_record_invalidates_cross_cache(self):
        runner, plan, before = self.run_it()
        plan['records'][0]['billing_history'] = 'PENDENTE'
        out = runner.run(plan, api_key=SECRET)
        self.assertEqual(out['calls'], before['calls'] + 1)
        self.assertEqual(out['records'][0]['status'], 'PENDENTE')

    def test_timeout_not_blindly_retried(self):
        provider = FakeProvider(fail='CONEXAO_INDETERMINADA')
        runner, plan, _ = self.run_it(provider=provider)
        runner.run(plan, api_key=SECRET)
        self.assertEqual(len(provider.requests), 1)

    def test_http_key_error_stays_pending(self):
        _, _, out = self.run_it(provider=FakeProvider(fail='HTTP_401'))
        self.assertEqual(out['errors'][0]['code'], 'HTTP_401')
        self.assertEqual(out['records'][0]['status'], 'PENDENTE')

    def test_excess_context_is_not_truncated(self):
        _, _, out = self.run_it(limits=Limits(request_byte_limit=1000))
        self.assertEqual(out['calls'], 0)
        self.assertEqual(out['errors'][0]['code'], 'CONTEXTO_EXCESSIVO_REQUER_DIVISAO')

    def test_key_in_material_never_sent(self):
        pdf = inventory()
        pdf['pages'][0]['text'] += SECRET
        provider = FakeProvider()
        _, _, out = self.run_it(files=[pdf], provider=provider)
        self.assertEqual(len(provider.requests), 0)
        self.assertEqual(out['errors'][0]['code'], 'CREDENCIAL_ENCONTRADA_NO_MATERIAL')


class WorkbookPlan(unittest.TestCase):
    def review(self):
        return Workflow().run_it()[2]

    def test_create_has_reference_columns_and_blank_unknown_money(self):
        raw = record()
        raw['tariff_key'] = 'PENDENTE'
        _, _, review = Workflow().run_it(records=[raw])
        plan = plan_write([raw], review, mode='new', review_date='2026-10-21')
        self.assertEqual(len(plan['schema']['headers']), 37)
        self.assertEqual(plan['schema']['headers'].count('Observação'), 2)
        self.assertIsNone(plan['append'][0]['values'][11])
        self.assertEqual(plan['original_rows_to_modify'], [])

    def test_append_preserves_existing_and_avoids_phase_duplicate(self):
        review = self.review()
        result = review['records'][0]
        old = {'last_row': 10, 'imports': set(), 'records': [
            {'row': 2, 'process': PROCESS, 'phase_key': result['phase_key'], 'amount': 999, 'status': 'JÁ FATURADO'}]}
        with patch('plan_workbook.read_existing', return_value=old):
            plan = plan_write([record()], review, mode='append', existing='original.xlsx', review_date='2026-10-21')
        self.assertEqual(plan['append'], [])
        self.assertEqual(plan['conflicts'][0]['existing_rows'][0]['amount'], 999)
        self.assertEqual(plan['original_rows_to_modify'], [])

    def test_same_process_new_phase_can_append(self):
        old = {'last_row': 10, 'imports': set(), 'records': [
            {'row': 2, 'process': PROCESS, 'phase_key': '50000010020258210001_4532022_RECURSAL_ORD',
             'amount': 100, 'status': 'PENDENTE'}]}
        with patch('plan_workbook.read_existing', return_value=old):
            plan = plan_write([record()], self.review(), mode='append', existing='original.xlsx', review_date='2026-10-21')
        self.assertEqual(plan['append'][0]['excel_row'], 11)

    def test_legacy_same_process_without_phase_needs_reconciliation(self):
        old = {'last_row': 2, 'imports': set(), 'records': [
            {'row': 2, 'process': PROCESS, 'phase_key': None, 'amount': 100, 'status': 'PENDENTE'}]}
        with patch('plan_workbook.read_existing', return_value=old):
            plan = plan_write([record()], self.review(), mode='append', existing='original.xlsx', review_date='2026-10-21')
        self.assertFalse(plan['append'])
        self.assertTrue(plan['conflicts'])

    def test_legacy_contract_suffix_does_not_duplicate_phase(self):
        review = self.review()
        phase = review['records'][0]['phase_key']
        old = {'last_row': 2, 'imports': set(), 'records': [
            {'row': 2, 'process': PROCESS, 'phase_key': phase.replace('_4532022_', '_4532022RSSC_'),
             'amount': 450, 'status': 'PENDENTE'}]}
        with patch('plan_workbook.read_existing', return_value=old):
            plan = plan_write([record()], review, mode='append', existing='original.xlsx', review_date='2026-10-21')
        self.assertFalse(plan['append'])
        self.assertEqual(len(plan['conflicts']), 1)

    def test_legacy_phase_aliases(self):
        from decidir_lote import normalize_phase_key
        prefix = '50000010020258210001_4532022_'
        self.assertEqual(normalize_phase_key(prefix + 'DEFESA_IMPUGNACAO'), prefix + 'DEFESA')
        self.assertEqual(normalize_phase_key(prefix + '22_A'), prefix + '2022_22_A')
        self.assertIsNone(normalize_phase_key(prefix + 'GRUPO_DESCONHECIDO'))


if __name__ == '__main__':
    unittest.main()
