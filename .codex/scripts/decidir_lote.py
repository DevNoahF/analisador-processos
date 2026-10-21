#!/usr/bin/env python3
"""Conferir regras SHR em fatos estruturados. Não ler autos nem autorizar cobrança."""
import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path
import re
import unicodedata

UFS = set('AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO'.split())
C20, C22, C25 = '1700165/2020', '453/2022 (RS-SC)', '2025'
CNJ = re.compile(r'^\d{7}-\d{2}\.(\d{4})\.\d\.\d{2}\.\d{4}$')


def norm(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value or ''))
                   if not unicodedata.combining(c)).strip().upper().replace(' ', '_')


def iso(value):
    if value in (None, ''):
        return None
    if not isinstance(value, str):
        raise ValueError('Usar data ISO AAAA-MM-DD.')
    return date.fromisoformat(value)


def contract_key(contract):
    """ID financeiro estável; o rótulo territorial não faz parte da chave."""
    return {C20: '17001652020', C22: '4532022', C25: '2025'}.get(contract)


def normalize_phase_key(value):
    """Reconhecer apenas formatos conhecidos; desconhecido exige reconciliação."""
    match = re.fullmatch(r'(\d{20})_(4532022RSSC|4532022|17001652020|2025)_([A-Z0-9_]+)',
                         str(value or '').strip().upper())
    if not match:
        return None
    process, contract, phase = match.groups()
    contract = '4532022' if contract == '4532022RSSC' else contract
    if contract == '4532022':
        phase = {'DEFESA_IMPUGNACAO': 'DEFESA', '22_A': '2022_22_A',
                 '22_B': '2022_22_B', '22_D': '2022_22_D'}.get(phase, phase)
    known = {r['phase_group'] for r in load_tariffs().values()} | {'ENCERRAMENTO'}
    if phase not in known:
        return None
    return '_'.join([process, contract, phase])


def contract_for(uf, subs, process):
    """Aplicar a precedência territorial usada na planilha de referência."""
    uf = norm(uf)
    if uf not in UFS:
        return 'PENDENTE UF'
    if uf in {'RS', 'SC'}:
        return C22
    match = CNJ.fullmatch(str(process or ''))
    if match and match.group(1) == '2026':
        return C25
    if subs is None:
        return 'PENDENTE SUBS'
    return C20 if subs < date(2025, 12, 23) else C25


def no_activity_rule(activity, subs, closure, extinction, verified=False, reviewed=False):
    activity = norm(activity)
    if activity == 'SIM':
        return 'ATUACAO_COMPROVADA'
    if activity != 'NAO' or not verified or not reviewed:
        return 'PENDENTE_VERIFICAR_ATUACAO'
    if subs is None or closure is None:
        return 'PENDENTE_SUBS_BAIXA'
    if extinction and closure < extinction:
        return 'PENDENTE_CRONOLOGIA'
    if closure == subs:
        return 'PENDENTE_MESMA_DATA'
    if extinction and extinction < subs < closure:
        return 'PENDENTE_EXTINCAO_ANTES_BAIXA_DEPOIS'
    return 'ANALISE_22K' if closure < subs else 'ENCERRAMENTO'


def load_tariffs(path=None):
    path = Path(path) if path else Path(__file__).resolve().parents[1] / 'references/tarifas.json'
    rows = json.loads(path.read_text(encoding='utf-8'))['tariffs']
    result = {r['key']: r for r in rows}
    if len(result) != len(rows):
        raise ValueError('Chaves duplicadas na tabela de tarifas.')
    return result


def decide(record, tariffs):
    pending = []
    dates = {}
    for field in ['subs_date', 'closure_date', 'extinction_date', 'act_date']:
        try:
            dates[field] = iso(record.get(field))
        except (ValueError, TypeError):
            dates[field] = None
            pending.append(f'Data inválida: {field}. Usar AAAA-MM-DD.')
    subs, closure, extinction, act = (dates[k] for k in ['subs_date', 'closure_date', 'extinction_date', 'act_date'])
    process = str(record.get('process') or '')
    contract = contract_for(record.get('uf'), subs, process)
    if not CNJ.fullmatch(process):
        pending.append('CNJ ausente ou fora do formato: verificar capa e processo do lançamento.')
    if contract.startswith('PENDENTE'):
        pending.append(contract)
    activity = norm(record.get('shr_activity'))
    rule = no_activity_rule(activity, subs, closure, extinction,
                            record.get('absence_verified') is True,
                            record.get('review_complete') is True)
    if rule.startswith('PENDENTE'):
        pending.append(rule)
    if activity == 'SIM' and not record.get('shr_evidence'):
        pending.append('Falta evidência de atuação efetivamente apresentada pela SHR.')
    if subs is None or not record.get('subs_source'):
        pending.append('Falta data/fonte do Subs específico SHR ou tombamento confirmado.')
    if extinction and closure and closure < extinction:
        pending.append('Baixa anterior à extinção informada: conferir cronologia.')

    key = str(record.get('tariff_key') or '')
    if rule == 'ANALISE_22K':
        if key and key != 'GERAL_22_K':
            pending.append('Tarifa informada diverge da análise 22-k antes do Subs.')
        key = 'GERAL_22_K'
    tariff = tariffs.get(key)
    amount = None
    phase = None
    incompatible = False
    if tariff is None:
        pending.append('Falta tabela/hipótese aplicável; não importar preço de outro contrato.')
    else:
        phase = tariff['phase_group']
        if key == 'PENDENTE':
            phase = 'ENCERRAMENTO'
        if tariff['contract'] not in {contract, 'Geral'}:
            pending.append('Contrato da tarifa não corresponde ao contrato do processo.')
            incompatible = True
        if rule == 'ENCERRAMENTO' and phase != 'ENCERRAMENTO':
            pending.append('Sem atuação e baixa posterior ao Subs: conferir tarifa de encerramento.')
            incompatible = True
        if key == 'GERAL_22_K' and rule != 'ANALISE_22K':
            pending.append('22-k exige ausência confirmada de atuação e baixa anterior ao Subs.')
            incompatible = True
        if (key.startswith('2022_10_') or key.startswith('2020_13_')):
            direct = norm(record.get('bank_role')) == 'EXEQUENTE'
            incident = (norm(record.get('principal_bank_role')) == 'EXEQUENTE'
                        and bool(record.get('principal_role_evidence')))
            if not (direct or incident):
                pending.append('Tabela de execução ativa exige banco exequente na relação principal.')
                incompatible = True
        if phase == 'ENCERRAMENTO':
            if closure is None:
                pending.append('Falta baixa definitiva vigente.')
            if record.get('closure_cancelled') is True:
                pending.append('Baixa cancelada: localizar a baixa definitiva atualmente vigente.')
                incompatible = True
            if record.get('final_outcome_confirmed') is not True:
                pending.append('Falta resultado final, incluindo acórdão quando houve recurso.')
            if norm(record.get('obligations_fulfilled')) != 'SIM':
                pending.append('Encerramento exige cumprimento total das obrigações comprovado.')
        if key.startswith('2020_') and key.endswith('_BAIXA') and key != '2020_16_BAIXA':
            if record.get('closure_without_success') is not True:
                pending.append('Baixa 2020: comprovar a condição sem êxito; conferir possível bônus substitutivo.')
        if key.startswith(('2020_26_', '2022_23_')):
            passive = {'REU', 'REQUERIDO', 'EXECUTADO', 'PASSIVO'}
            role = norm(record.get('bank_role'))
            principal_role = norm(record.get('principal_bank_role'))
            if role not in passive and not (principal_role in passive and record.get('principal_role_evidence')):
                pending.append('Bônus passivo exige polo passivo do banco na relação principal comprovado.')
                if role in {'AUTOR', 'EXEQUENTE', 'ATIVO'}:
                    incompatible = True
            if key.endswith('_IMPROCEDENCIA') and record.get('all_claims_dismissed') is not True:
                pending.append('Comprovar improcedência total de todos os pedidos no resultado final.')
            if any(key.endswith(s) for s in ['_DANO_MORAL', '_DANO_COMUM', '_DANO_JEC']):
                if not (record.get('moral_damages_requested') is True and record.get('moral_damages_excluded') is True):
                    pending.append('Bônus de dano moral exige pedido efetivo e afastamento no resultado final.')
            if key.endswith(('_ACORDO_DEFESA', '_ACORDO_SENTENCA')):
                before_defense = key.endswith('_ACORDO_DEFESA')
                milestone = 'defense_date' if before_defense else 'first_instance_decision_date'
                try:
                    agreement = iso(record.get('agreement_homologation_date'))
                    boundary = iso(record.get(milestone))
                except (ValueError, TypeError):
                    agreement, boundary = None, None
                no_boundary = ('defense_not_filed_verified' if before_defense else 'first_decision_not_issued_verified')
                verified_no_boundary = record.get(no_boundary) is True and bool(record.get('agreement_timing_source'))
                if (not agreement or not record.get('agreement_timing_source')
                        or (boundary is None and not verified_no_boundary)
                        or (boundary is not None and agreement >= boundary)):
                    pending.append('Acordo: comprovar homologação antes do marco contratual, com fonte e datas distintas.')
        if tariff.get('required_notes') and record.get('notes_complete') is not True:
            pending.append('Conferir notas contratuais: ' + ', '.join(map(str, tariff['required_notes'])))
        if key in {'2020_27_BONUS_ATIVO', '2022_24_BONUS_ATIVO'}:
            pending.append('Encaminhar bônus ativo e critérios de recuperação à coordenação.')
        if key == '2022_22_A':
            if record.get('payment_without_fine') is not True:
                pending.append('Comprovar pagamento de condenação/sucumbência sem multa.')
            if record.get('payment_without_fine') is False:
                incompatible = True
            if norm(record.get('payment_kind')) not in {'CONDENACAO', 'SUCUMBENCIA'}:
                pending.append('Custas e depósito genérico não comprovam a hipótese da tabela 22-a.')
                incompatible = True
        if key == '2022_22_D':
            if record.get('representation_replaced') is not True or record.get('ongoing_at_receipt') is not True:
                pending.append('Comprovar substituição de representação em processo em andamento.')
        auth = tariff['authorization']
        if auth == 'A_CONFIRMAR':
            pending.append('Exigência de autorização ainda a confirmar.')
        elif auth == 'SIM':
            if not (record.get('authorization_attached') is True
                    and record.get('authorization_prior') is True
                    and record.get('authorization_source')):
                pending.append('Falta autorização prévia expressa, anexada e vinculada ao ato.')
        if tariff['amount_brl'] is None:
            pending.append('Valor/critério não definido: manter célula monetária vazia.')
        elif not incompatible:
            amount = tariff['amount_brl']

    if act is None:
        pending.append('Falta data do ato ou implementação da condição remunerável.')
    elif subs and act < subs:
        pending.append('Ato anterior ao Subs: não aplicar remuneração retroativa.')
    if not record.get('evidence'):
        pending.append('Faltam fontes do lançamento (PDF/evento/documento/páginas).')
    if not record.get('responsible'):
        pending.append('Falta responsável interno confirmado.')
    history = norm(record.get('billing_history'))
    if history not in {'SIM', 'NAO'}:
        pending.append('Falta conferência do histórico financeiro da fase.')
    for field, label in [
        ('single_pdf_checked', 'Conferir o PDF único de faturamento.'),
        ('file_named_correctly', 'Conferir nome do PDF e convenção de faturamento.'),
        ('documentation_complete', 'Documentação exigida incompleta ou não conferida.'),
        ('qualification_confirmed', 'Enquadramento da hipótese ainda não confirmado.'),
    ]:
        if record.get(field) is not True:
            pending.append(label)
    if norm(record.get('obligations_fulfilled')) not in {'SIM', 'NAO_APLICAVEL'}:
        pending.append('Falta conferir cumprimento das obrigações aplicáveis.')
    phase_key = None
    if phase and CNJ.fullmatch(process) and not contract.startswith('PENDENTE'):
        phase_key = '_'.join([re.sub(r'\D', '', process), contract_key(contract), phase])
    pending = list(dict.fromkeys(pending))
    status = 'JÁ FATURADO' if history == 'SIM' else 'PENDENTE' if pending else 'APTO À CONFERÊNCIA FINAL'
    return {'process': process, 'contract': contract,
            'analysis_phase': 2 if norm(record.get('uf')) in {'RS', 'SC'} else record.get('analysis_phase'),
            'no_activity_rule': rule, 'tariff_key': key or None, 'phase_key': phase_key,
            'table': tariff['table'] if tariff else None, 'act': tariff['act'] if tariff else None,
            'amount_brl': amount, 'status': status, 'pending': pending,
            'source': tariff['source'] if tariff else None, 'evidence': record.get('evidence', [])}


def decide_batch(records, tariffs=None):
    if not isinstance(records, list) or not records or not all(isinstance(r, dict) for r in records):
        raise ValueError('Fornecer records como lista não vazia de objetos.')
    tariffs = load_tariffs() if tariffs is None else tariffs
    outputs = [decide(record, tariffs) for record in records]
    counts = Counter(o['phase_key'] for o in outputs if o['phase_key'])
    for out in outputs:
        if out['phase_key'] and counts[out['phase_key']] > 1:
            out['pending'].append('Fase/grupo de encerramento repetido: consolidar evidências e não acumular cobranças.')
            if out['status'] != 'JÁ FATURADO':
                out['status'] = 'PENDENTE'
    return {'records': outputs, 'summary': {'records': len(outputs),
            'status_counts': dict(Counter(o['status'] for o in outputs))},
            'scope': 'Conferência de fatos fornecidos. Não lê autos e não autoriza cobrança.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--tariffs', type=Path)
    args = parser.parse_args()
    raw = json.loads(args.input.read_text(encoding='utf-8'))
    result = decide_batch(raw['records'] if isinstance(raw, dict) else raw, load_tariffs(args.tariffs))
    content = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding='utf-8')
    else:
        print(content, end='')


if __name__ == '__main__':
    main()
