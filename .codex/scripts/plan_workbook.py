"""Ler XLSX sem alterar e planejar criação/acréscimo; escritor deve seguir planilha.md.

Sem openpyxl, sem overwrite de linhas. Plano JSON é intermediário privado, não XLSX.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / 'assets/workbook-schema.json').read_text(encoding='utf-8'))
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}


def column_index(address):
    result = 0
    for letter in re.match(r'[A-Z]+', address).group():
        result = result * 26 + ord(letter) - 64
    return result - 1


def read_existing(path):
    """Somente leitura. O escritor importa o original completo, não este recorte."""
    with ZipFile(path) as archive:
        if any(x.file_size > 150_000_000 for x in archive.infolist()):
            raise ValueError('XLSX excessivo: encaminhar à importação controlada do site.')
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            root = ET.fromstring(archive.read('xl/sharedStrings.xml'))
            strings = [''.join(n.itertext()) for n in root.findall('s:si', NS)]
        book = ET.fromstring(archive.read('xl/workbook.xml'))
        rels = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        targets = {r.attrib['Id']: r.attrib['Target'] for r in rels}
        sheets = {}
        for item in book.findall('s:sheets/s:sheet', NS):
            target = targets[item.attrib['{' + NS['r'] + '}id']]
            target = target.lstrip('/') if target.startswith('/') else 'xl/' + target
            if '..' in target.split('/') or target not in archive.namelist():
                raise ValueError('Relação XLSX inválida.')
            content = ET.fromstring(archive.read(target))
            rows = []
            for row in content.findall('s:sheetData/s:row', NS):
                cells = {}
                for cell in row.findall('s:c', NS):
                    value = cell.find('s:v', NS)
                    value = value.text if value is not None else None
                    if cell.attrib.get('t') == 's' and value is not None:
                        value = strings[int(value)]
                    elif cell.attrib.get('t') == 'inlineStr':
                        value = ''.join(t.text or '' for t in cell.findall('.//s:t', NS))
                    cells[column_index(cell.attrib['r'])] = value
                rows.append({'row': int(row.attrib['r']), 'cells': cells})
            sheets[item.attrib['name']] = rows
    if SCHEMA['sheet'] not in sheets:
        raise ValueError('Aba FORÇA TAREFA 2 ausente: mapear explicitamente, sem adivinhar.')
    main = sheets[SCHEMA['sheet']]
    header = next((r for r in main if r['row'] == 1), None)
    # A referência original tem 23 campos; o modelo ampliado tem 37.
    if not header or any(header['cells'].get(i) != SCHEMA['headers'][i] for i in range(23)):
        raise ValueError('Cabeçalhos diferentes da referência: exigir mapeamento explícito por posição/ocorrência.')
    for i in range(23, 37):
        if header['cells'].get(i) not in {None, '', SCHEMA['headers'][i]}:
            raise ValueError('Controle adicional em posição incompatível; preservar e mapear antes de escrever.')
    seen = []
    for row in main:
        c = row['cells']
        if row['row'] > 1 and c.get(5):
            seen.append({'row': row['row'], 'process': c.get(5), 'phase_key': c.get(29),
                         'status': c.get(1), 'amount': c.get(11)})
    imports = {(r['cells'].get(0), r['cells'].get(1)) for r in sheets.get(SCHEMA['supervision_sheet'], [])
               if r['row'] > 1}
    return {'records': seen, 'last_row': max((r['row'] for r in main), default=1), 'imports': imports}


def yes(value):
    return 'Sim' if value is True else 'Pendente'


def cell_text(value):
    if value is None:
        return None
    if isinstance(value, list):
        return '\n'.join(cell_text(v) or '' for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def new_row(raw, decision, review_date):
    from decidir_lote import load_tariffs
    tariff = load_tariffs().get(decision['tariff_key'], {})
    auth = tariff.get('authorization', 'A_CONFIRMAR')
    auth_label = {'SIM': 'Sim', 'NAO': 'Não', 'A_CONFIRMAR': 'A confirmar'}.get(auth, 'A confirmar')
    values = [1, decision['status'], decision['contract'], raw.get('responsible'), raw.get('uf'),
        decision['process'], raw.get('billing_history', 'Pendente'), raw.get('adverse_party'), raw.get('act_date'),
        decision['table'], decision['act'], decision['amount_brl'], auth_label,
        'Não aplicável' if auth == 'NAO' else yes(raw.get('authorization_attached')),
        yes(raw.get('single_pdf_checked')), yes(raw.get('file_named_correctly')),
        raw.get('required_documentation'), raw.get('procedure'), raw.get('observation'), review_date,
        'Pendente', raw.get('vios_observation'), None, raw.get('subs_date'), raw.get('closure_date'),
        raw.get('shr_activity', 'Pendente'), cell_text(decision['evidence']), cell_text(decision['pending']),
        decision['tariff_key'], decision['phase_key'], cell_text(raw.get('subs_source')), raw.get('extinction_date'),
        yes(raw.get('documentation_complete')), yes(raw.get('qualification_confirmed')),
        raw.get('obligations_fulfilled', 'Pendente'), decision['no_activity_rule'], decision['analysis_phase']]
    # O escritor deve usar valores literais, nunca interpretar texto do PDF como fórmula.
    return values


def plan_write(raw_records, review, *, mode, review_date, existing=None):
    from decidir_lote import normalize_phase_key
    if mode not in {'new', 'append'} or (mode == 'append') != bool(existing):
        raise ValueError('Escolher new sem arquivo ou append com arquivo existente.')
    from datetime import date
    date.fromisoformat(review_date)
    old = read_existing(existing) if existing else {'records': [], 'last_row': 1, 'imports': set()}
    by_id = {r['record_id']: r for r in raw_records}
    if len(by_id) != len(raw_records) or {r['record_id'] for r in review['records']} != set(by_id):
        raise ValueError('Linhas da análise e supervisão não correspondem.')
    append, conflicts, supervision = [], [], []
    phase_counts = Counter(normalize_phase_key(r['phase_key']) for r in review['records'] if normalize_phase_key(r['phase_key']))
    for result in review['records']:
        record_id, phase, process = result['record_id'], result['phase_key'], result['process']
        raw = by_id[record_id]
        if not result.get('supervision'):
            raise ValueError('Linha sem resultado explícito da supervisão.')
        canonical_phase = normalize_phase_key(phase)
        existing_matches = [r for r in old['records'] if
                            (canonical_phase and normalize_phase_key(r['phase_key']) == canonical_phase)
                            or (r['process'] == process and
                                (not canonical_phase or not normalize_phase_key(r['phase_key'])))]
        already_imported = (review['job_id'], record_id) in old['imports']
        if existing_matches or already_imported or (canonical_phase and phase_counts[canonical_phase] > 1):
            conflicts.append({'record_id': record_id, 'phase_key': phase, 'existing_rows': existing_matches,
                              'reason': 'JA_IMPORTADO' if already_imported else 'RECONCILIAR_FASE_SEM_SOBRESCREVER'})
            continue
        if result['status'] == 'APTO À CONFERÊNCIA FINAL' and result['supervision']['status'] != 'REVISAO_SEM_DIVERGENCIA':
            raise ValueError('Status apto incompatível com pendência supervisora.')
        append.append({'excel_row': old['last_row'] + len(append) + 1, 'record_id': record_id,
                       'values': new_row(raw, result, review_date)})
        supervision.append([review['job_id'], record_id, phase, process, result['supervision']['status'],
                            review['provider'], review['model'], review['rules_hash'],
                            cell_text(result['source_ids']), cell_text(result['pending'])])
    return {'mode': mode, 'schema': SCHEMA, 'append': append, 'conflicts': conflicts,
            'supervision_rows': supervision, 'original_rows_to_modify': [],
            'rules': json.loads((ROOT / 'references/tarifas.json').read_text(encoding='utf-8')),
            'instructions': 'Importar original completo em append. Acrescentar apenas estas linhas; salvar cópia atômica. Não sobrescrever conflitos.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('records', type=Path)
    parser.add_argument('review', type=Path)
    parser.add_argument('--mode', choices=['new', 'append'], required=True)
    parser.add_argument('--existing', type=Path)
    parser.add_argument('--review-date', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = json.loads(args.records.read_text(encoding='utf-8'))
    raw = raw['records'] if isinstance(raw, dict) else raw
    review = json.loads(args.review.read_text(encoding='utf-8'))
    plan = plan_write(raw, review, mode=args.mode, review_date=args.review_date, existing=args.existing)
    args.output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
