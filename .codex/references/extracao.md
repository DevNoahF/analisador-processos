# Extração e comprovação no eproc

Executar com Python e PyMuPDF disponíveis:

```bash
python scripts/extract_eproc.py --output /diretorio/intermediario arquivo1.pdf arquivo2.pdf
```

Usar os caminhos fornecidos com argumentos separados e aspas corretas. O script
produz JSON por PDF, sem modificar o original. Se faltar PyMuPDF, usar as ferramentas
da skill de PDF e registrar a limitação, sem instalar pacotes por conta própria.

## Inventário

Extrair capas/candidatos de CNJ, eventos, documentos, páginas físicas, texto e
alertas de OCR/conferência. Agrupar por processo + evento + código. Reconhecer
título espaçado de substabelecimento e decodificar entidades HTML dos códigos.
Contar imagens efetivamente exibidas com `get_image_info`, pois a lista de recursos
`get_images` pode repetir imagens do PDF inteiro em páginas que não as mostram.
Isso evita OCR/conferência desnecessários sem dispensar imagens realmente visíveis.
O script não interpreta decisões, não confirma destinatário SHR, não escolhe a data
do Subs e não declara inexistência de atuação.

## Leitura

Renderizar páginas representativas e todas as evidências relevantes para valores,
datas, decisões e assinaturas. Limiares do script são triagem; não provam leitura.
Conferir imagens embutidas quando delas depender uma condição, mesmo com texto
nativo legível. Rodapé pode ser a única camada textual. Fonte corrompida pode gerar
muitos caracteres de controle em lugar do texto visível.

Aplicar OCR local com Tesseract ou recurso disponível nas páginas necessárias,
preservando o PDF original e rastreando a origem do OCR. Não enviar autos a serviço
externo por padrão. Conferir datas/valores do OCR contra as imagens.

## Relações e alertas

Separar processo da capa, CNJ da linha da planilha, originários, cumprimentos e
recursos. Datas no corpo podem ser de jurisprudência ou procuração anterior;
datas oficiais de evento identificam protocolos. Não escolher a primeira data
encontrada como Subs ou data do ato.

Sinalizar divergência de nome do PDF/capa; UF/CNJ/tribunal incorretos no cabeçalho
da peça; Subs de outro escritório; baixa cancelada; baixa de recurso dentro de
ação ativa; improcedência de primeiro grau sem acórdão posterior; pagamento sem
prova de ausência de multa; páginas relevantes ilegíveis.

Código genérico de documento e nome de advogado em cadastro/intimação não provam
ato praticado. Para cada conclusão, manter página física e identificação da peça.
Registrar pendências específicas e continuar os demais registros.
