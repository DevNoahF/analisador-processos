#!/usr/bin/env python3
"""Verificar fronteiras contratuais e bloqueios financeiros com dados fictícios."""
from copy import deepcopy
from datetime import date
import unittest
from decidir_lote import C20, C22, contract_for, decide_batch, load_tariffs, no_activity_rule
from extract_eproc import analyze_page, clean

PROCESS = '5000001-00.2025.8.21.0001'


def complete():
    return {'process': PROCESS, 'uf': 'RS', 'subs_date': '2025-04-02',
            'subs_source': 'Documento específico SHR, página fictícia 12.',
            'shr_activity': 'SIM', 'shr_evidence': ['Peça SHR e protocolo fictícios.'],
            'act_date': '2025-05-05', 'evidence': ['Evento fictício 23, CONT2, pp. 20-25.'],
            'tariff_key': '2022_1_DEFESA', 'responsible': 'Responsável confirmado no controle interno',
            'billing_history': 'NAO', 'single_pdf_checked': True, 'file_named_correctly': True,
            'documentation_complete': True, 'qualification_confirmed': True,
            'obligations_fulfilled': 'NAO_APLICAVEL'}


class Contracts(unittest.TestCase):
    def test_cutoff(self):
        self.assertEqual(contract_for('SP', date(2025, 12, 22), PROCESS), C20)
        self.assertEqual(contract_for('SP', date(2025, 12, 23), PROCESS), '2025')

    def test_territorial_precedence(self):
        for uf in ['RS', 'SC']:
            self.assertEqual(contract_for(uf, None, PROCESS.replace('2025', '2026')), C22)

    def test_cnj_year_and_unknown_inputs(self):
        self.assertEqual(contract_for('SP', None, PROCESS.replace('2025', '2026')), '2025')
        self.assertEqual(contract_for('SP', None, PROCESS), 'PENDENTE SUBS')
        self.assertEqual(contract_for('', date(2025, 1, 1), PROCESS), 'PENDENTE UF')


class Absence(unittest.TestCase):
    def rule(self, closure, extinction=None, **kw):
        return no_activity_rule('NAO', date(2026, 1, 10), closure, extinction,
                                kw.get('verified', True), kw.get('reviewed', True))

    def test_before_after_same(self):
        self.assertEqual(self.rule(date(2026, 1, 9)), 'ANALISE_22K')
        self.assertEqual(self.rule(date(2026, 1, 11)), 'ENCERRAMENTO')
        self.assertEqual(self.rule(date(2026, 1, 10)), 'PENDENTE_MESMA_DATA')

    def test_unverified_absence_and_chronology(self):
        self.assertEqual(self.rule(date(2026, 1, 9), reviewed=False), 'PENDENTE_VERIFICAR_ATUACAO')
        self.assertEqual(self.rule(date(2026, 1, 11), date(2026, 1, 9)), 'PENDENTE_EXTINCAO_ANTES_BAIXA_DEPOIS')
        self.assertEqual(self.rule(date(2026, 1, 9), date(2026, 1, 11)), 'PENDENTE_CRONOLOGIA')
        self.assertEqual(self.rule(None), 'PENDENTE_SUBS_BAIXA')


class Billing(unittest.TestCase):
    def one(self, record):
        return decide_batch([record])['records'][0]

    def test_complete_then_missing_prerequisite(self):
        r = complete()
        self.assertEqual(self.one(r)['status'], 'APTO À CONFERÊNCIA FINAL')
        r['documentation_complete'] = False
        self.assertEqual(self.one(r)['status'], 'PENDENTE')

    def test_unknown_history_is_not_unbilled(self):
        r = complete(); r.pop('billing_history')
        self.assertEqual(self.one(r)['status'], 'PENDENTE')
        r['billing_history'] = 'SIM'
        self.assertEqual(self.one(r)['status'], 'JÁ FATURADO')

    def test_duplicate_is_not_a_new_phase(self):
        a = complete(); b = deepcopy(a); b['evidence'] = ['Outra peça da mesma fase.']
        results = decide_batch([a, b])['records']
        self.assertTrue(all(r['status'] == 'PENDENTE' for r in results))
        self.assertEqual(results[0]['phase_key'], results[1]['phase_key'])

    def test_closure_and_bonus_share_exclusion_group(self):
        a = complete(); a.update(tariff_key='2022_1_BAIXA', closure_date='2026-03-01',
                                 act_date='2026-03-01', obligations_fulfilled='SIM', final_outcome_confirmed=True)
        b = deepcopy(a); b['tariff_key'] = '2022_23_IMPROCEDENCIA'
        results = decide_batch([a, b])['records']
        self.assertEqual(results[0]['phase_key'], results[1]['phase_key'])
        self.assertTrue(all(any('repetido' in p for p in r['pending']) for r in results))

    def test_passive_bank_cannot_use_active_execution(self):
        r = complete(); r.update(tariff_key='2022_10_DEFESA', bank_role='EXECUTADO')
        self.assertIsNone(self.one(r)['amount_brl'])

    def test_contract_mismatch_and_unknown_price_are_not_zero(self):
        r = complete(); r['tariff_key'] = '2020_1_BAIXA'
        self.assertIsNone(self.one(r)['amount_brl'])
        r['tariff_key'] = 'PENDENTE'
        self.assertIsNone(self.one(r)['amount_brl'])

    def test_payment_with_fine_not_22a(self):
        r = complete(); r.update(tariff_key='2022_22_A', payment_without_fine=False, payment_kind='CONDENACAO')
        self.assertIsNone(self.one(r)['amount_brl'])
        r.update(payment_without_fine=True, payment_kind='CUSTAS')
        self.assertIsNone(self.one(r)['amount_brl'])

    def test_22k_requires_prior_authorization(self):
        r = complete(); r.update(shr_activity='NAO', absence_verified=True, review_complete=True,
                                 closure_date='2025-04-01', tariff_key='GERAL_22_K')
        self.assertEqual(self.one(r)['amount_brl'], 50)
        self.assertEqual(self.one(r)['status'], 'PENDENTE')
        r.update(authorization_attached=True, authorization_prior=True, authorization_source='Autorização fictícia anterior.')
        self.assertEqual(self.one(r)['status'], 'APTO À CONFERÊNCIA FINAL')

    def test_invalid_date_does_not_abort_other_records(self):
        a = complete(); a['subs_date'] = '02/04/2025'
        b = complete(); b['process'] = '5000002-00.2025.8.21.0001'
        out = decide_batch([a, b])['records']
        self.assertEqual(out[0]['status'], 'PENDENTE')
        self.assertEqual(out[1]['status'], 'APTO À CONFERÊNCIA FINAL')

    def test_snapshot_values(self):
        t = load_tariffs()
        for key, expected in [('2022_1_DEFESA',450),('2022_10_BAIXA',400),('2020_7_BAIXA',240),('GERAL_22_K',50)]:
            self.assertEqual(t[key]['amount_brl'], expected)

    def test_cancelled_closure_cannot_use_closure_fee(self):
        r = complete()
        r.update(tariff_key='2022_1_BAIXA', closure_date='2026-03-01',
                 closure_cancelled=True, final_outcome_confirmed=True, obligations_fulfilled='SIM')
        out = self.one(r)
        self.assertEqual(out['status'], 'PENDENTE')
        self.assertIsNone(out['amount_brl'])

    def test_bonus_requires_specific_facts_and_passive_bank(self):
        r = complete()
        r.update(tariff_key='2022_23_IMPROCEDENCIA', closure_date='2026-03-01',
                 final_outcome_confirmed=True, obligations_fulfilled='SIM', bank_role='EXEQUENTE')
        out = self.one(r)
        self.assertIsNone(out['amount_brl'])
        self.assertTrue(any('todos os pedidos' in p for p in out['pending']))
        r.update(tariff_key='2020_26_DANO_MORAL', uf='SP', bank_role='REU')
        self.assertTrue(any('pedido efetivo' in p for p in self.one(r)['pending']))

    def test_agreement_equal_to_milestone_is_not_before(self):
        r = complete()
        r.update(tariff_key='2020_26_ACORDO_DEFESA', uf='SP', bank_role='REU',
                 closure_date='2026-03-01', final_outcome_confirmed=True, obligations_fulfilled='SIM',
                 agreement_homologation_date='2025-05-05', defense_date='2025-05-05',
                 agreement_timing_source='Cronologia fictícia confirmada.')
        self.assertTrue(any('marco contratual' in p for p in self.one(r)['pending']))

    def test_2020_closure_without_success_condition(self):
        r = complete()
        r.update(tariff_key='2020_1_BAIXA', uf='SP', closure_date='2026-03-01',
                 final_outcome_confirmed=True, obligations_fulfilled='SIM')
        self.assertTrue(any('sem êxito' in p for p in self.one(r)['pending']))


class Extraction(unittest.TestCase):
    def test_footer_alone_requires_body_review(self):
        out = analyze_page(f'Processo {PROCESS}/RS, Evento 3, PROCJUDIC1, Página 1', 1)
        self.assertEqual(out['body_alphanumeric_chars'], 0)
        self.assertIn('OCR_OU_CONFERENCIA_DO_CORPO', out['flags'])

    def test_corruption_and_spaced_subs(self):
        self.assertIn('TEXTO_CORROMPIDO', analyze_page('\x01' * 20 + 'texto') ['flags'])
        self.assertTrue(analyze_page('S U B S T A B E L E C I M E N T O')['possible_subs'])
        self.assertEqual(clean('APELA&Ccedil;&Atilde;O1'), 'APELAÇÃO1')


if __name__ == '__main__':
    unittest.main()
