#!/usr/bin/env python3
"""Inventariar PDFs eproc sem alterar originais ou decidir remuneração."""
import argparse
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import re
import unicodedata

CNJ = r'\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}'
FOOTER = re.compile(r'Processo\s+(' + CNJ + r')/([A-Z]{2}),\s*Evento\s+(\d+),\s*([^\n,]+),\s*P[áa]gina\s+(\d+)', re.I)
DATE_TIME = re.compile(r'\b\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2}\b')


def clean(text):
    return unicodedata.normalize('NFKC', html.unescape(html.unescape(text)))


def analyze_page(text, image_count=0):
    text = clean(text)
    body = FOOTER.sub('', text).strip()
    controls = sum(unicodedata.category(c).startswith('C') and c not in '\n\r\t' for c in body)
    letters_digits = sum(c.isalnum() for c in body)
    flags = []
    official = 'PÁGINA DE SEPARAÇÃO' in text.upper() or 'CAPA PROCESSO' in text.upper()
    if not official and letters_digits < 50:
        flags.append('OCR_OU_CONFERENCIA_DO_CORPO')
    if body and controls / len(body) > .02:
        flags.append('TEXTO_CORROMPIDO')
    if image_count:
        flags.append('IMAGENS_PODEM_CONTER_PROVAS_NAO_EXTRAIDAS')
    if official:
        flags.append('IDENTIFICACAO_OFICIAL_NAO_EQUIVALE_A_LEITURA_DAS_PECAS')
    compact = re.sub(r'\s+', '', text).upper()
    return {'text': text, 'body_alphanumeric_chars': letters_digits,
            'control_characters': controls, 'image_count': image_count,
            'flags': flags, 'possible_subs': 'SUBSTABELECIMENTO' in compact}


def inventory(pdf):
    try:
        import fitz
    except ImportError as exc:
        raise SystemExit('PyMuPDF indisponível. Usar as ferramentas da skill de PDF; não concluir ausência de atuação.') from exc
    pdf = Path(pdf)
    pages, covers, events, docs, alerts = [], [], [], {}, []
    with fitz.open(pdf) as reader:
        for idx, page in enumerate(reader):
            # get_images() pode listar recursos não exibidos, inclusive do PDF inteiro.
            displayed_images = page.get_image_info()
            info = analyze_page(page.get_text(), len(displayed_images))
            info['displayed_image_bounds'] = [list(image['bbox']) for image in displayed_images]
            info['pdf_page'] = idx + 1
            text = info['text']
            pages.append(info)
            # Only official cover markers supply primary candidates, not quoted CNJs.
            if 'CAPA PROCESSO' in text.upper() or re.search(r'N[ºo°]\s+do processo', text, re.I):
                found = re.search(r'N[ºo°](?:\s+do processo)?\s*(' + CNJ + ')', text, re.I)
                if found:
                    covers.append({'process': found.group(1), 'pdf_page': idx + 1})
            if 'PÁGINA DE SEPARAÇÃO' in text.upper():
                match = re.search(r'\bEvento\s+(\d+)\b', text)
                when = DATE_TIME.search(text)
                proc = re.search('(' + CNJ + r')/([A-Z]{2})', text)
                seq = text.split('Sequência Evento:', 1)[-1].strip()
                description = seq[:seq.find(when.group())].strip().replace('\n', ' ') if when and when.group() in seq else None
                remainder = text[when.end():].strip().splitlines() if when else []
                events.append({'event': int(match.group(1)) if match else None,
                               'process': proc.group(1) if proc else None,
                               'uf': proc.group(2) if proc else None,
                               'date_time': when.group() if when else None,
                               'description': description,
                               'user': remainder[0] if remainder else None,
                               'pdf_page': idx + 1, 'source_text': text})
            footers = list(FOOTER.finditer(text))
            if footers:
                match = footers[-1]
                proc, uf, event, code, inner = match.groups()
                key = (proc, int(event), clean(code).strip())
                if key not in docs:
                    docs[key] = {'process': proc, 'uf': uf, 'event': int(event),
                                 'code': key[2], 'pdf_pages': [], 'piece_pages': [], 'possible_subs': False}
                docs[key]['pdf_pages'].append(idx + 1)
                docs[key]['piece_pages'].append(int(inner))
                docs[key]['possible_subs'] |= info['possible_subs']
    processes = sorted({c['process'] for c in covers})
    if len(processes) != 1:
        alerts.append('CAPA_PRINCIPAL_AMBIGUA_OU_NAO_RECONHECIDA')
    primary = processes[0] if len(processes) == 1 else None
    named = re.search(CNJ, pdf.name)
    if primary and named and named.group() != primary:
        alerts.append('NOME_ARQUIVO_DIVERGE_DO_PROCESSO_DA_CAPA')
    event_dates = {(e['process'], e['event']): e['date_time'] for e in events}
    for doc in docs.values():
        doc['event_date_time'] = event_dates.get((doc['process'], doc['event']))
    with pdf.open('rb') as source:
        sha256 = hashlib.file_digest(source, 'sha256').hexdigest()
    return {'file_name': pdf.name, 'sha256': sha256,
            'page_count': len(pages), 'primary_process': primary, 'covers': covers,
            'alerts': alerts, 'events': events, 'documents': list(docs.values()), 'pages': pages,
            'limitations': 'Triagem de extração, não leitura integral nem prova de ausência de atuação. Conferir imagens, OCR e fontes.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdfs', nargs='+', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for index, pdf in enumerate(args.pdfs, 1):
        result = inventory(pdf)
        destination = args.output / f'{index:03d}_{pdf.stem}.json'
        destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'output': str(destination), 'pages': result['page_count'],
                          'process': result['primary_process'], 'events': len(result['events']),
                          'alerts': result['alerts']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
