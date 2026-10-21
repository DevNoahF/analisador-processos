# Contrato de preenchimento da planilha

## Conteúdo

1. Campos do modelo
2. Criar ou acrescentar
3. Aba REGRAS
4. Dados para o motor de decisão

## Campos do modelo

Preservar o arquivo recebido. Na estrutura de referência, usar a aba `FORÇA TAREFA 2`.
Mapear cabeçalhos e posições antes de escrever e preservar cabeçalhos repetidos.

| Coluna | Cabeçalho | Preenchimento |
|---|---|---|
| A | Qntd. | 1 por lançamento remunerável/candidato |
| B | Status | PENDENTE, JÁ FATURADO ou APTO À CONFERÊNCIA FINAL |
| C | Contrato | Regra territorial e Subs, não data da petição |
| D | Advogado responsável | Responsável interno confirmado, não presumir pelo signatário |
| E | UF | Fonte oficial do processo |
| F | Processo (CNJ) | Processo ao qual pertence o lançamento |
| G | Atos já faturados | Sim/Não/Pendente após consulta ao histórico |
| H | Parte adversa | Parte(s), preservando espólio/inventariante |
| I | Data do ato | Protocolo/implementação da condição, com fonte |
| J | Tabela/Edital | Contrato + tabela ou pendência |
| K | Ato faturável | Hipótese contratual; indicar caráter preliminar |
| L | Valor/Critério | Número ou critério verificável; vazio se desconhecido |
| M | Autorização exigida? | Sim/Não/A confirmar |
| N | Autorização anexada? | Sim com documento; Não aplicável se dispensada |
| O | PDF único conferido? | Não presumir pelo recebimento dos autos |
| P | PDF nomeado corretamente? | Conferir CNJ e convenção exigida |
| Q | Documentação exigida | Evidências necessárias; não inventar exigência contratual |
| R | Procedimento/Categoria | Classe, natureza e polo do banco |
| S | Observação | Enquadramento, ressalvas e cronologia |
| T | Data da revisão | Data real da análise no fuso do usuário |
| U | ENCERRAR VIOS? | Pendente, salvo orientação e condições específicas |
| V | Observação | Condições internas de encerramento |
| W | Data da revisão | Revisão interna/VIOS; não duplicar T sem prova |
| X | Data do Subs | Documento/tombamento específico confirmado |
| Y | Data da baixa definitiva | Última baixa válida do processo correto |
| Z | Atuação SHR comprovada? | Sim/Não/Pendente |
| AA | Evidência do ato | PDF + evento + código + páginas físicas |
| AB | Pendências para faturar | Especificar o que falta |
| AC | Chave da tarifa | Chave da aba REGRAS, com letras/números/_ |
| AD | Chave de controle da fase | CNJ + contrato + grupo, sem evento |
| AE | Fonte da data do Subs | Documento, outorgados, data e evento/página |
| AF | Data da extinção | Separar da baixa e cumprimento das obrigações |
| AG | Documentação completa? | Sim somente após conferir todas as exigências |
| AH | Enquadramento confirmado? | Sim com hipótese e condições comprovadas |
| AI | Obrigações cumpridas? | Sim/Não aplicável/Pendente, com prova |
| AJ | Regra sem atuação | Atuação comprovada/Análise 22-k/Encerramento/pendência |
| AK | Fase da análise | 2 para RS/SC; demais conforme instrução do lote |

No modo **acrescentar**, não sobrescrever linhas existentes. Em reprocessamento,
usar a chave da fase para localizar conflitos, apresentar diferenças e agregar
evidências somente depois de resolução explícita. Não criar nova cobrança só porque
o PDF, evento ou `record_id` mudou. Exceção por ocorrência exige previsão expressa
e ocorrência identificada. Ampliar somente controles necessários; preservar histórico.

## Criar ou acrescentar

O modelo sem dados está em `assets/workbook-schema.json`. Preservar os 37 campos,
inclusive dois cabeçalhos `Observação` e dois `Data da revisão` por **posição**.
O modo de criação usa esse esquema, cabeçalho verde e tabela REGRAS com as tarifas
da mesma versão do motor. O modo de acréscimo importa o XLSX inteiro e trabalha
numa cópia. Não reconstruir o original usando apenas dados extraídos em JSON.

`scripts/plan_workbook.py` é leitor/planejador, não escritor XLSX. Ele identifica
linhas existentes e gera dados novos, controles de supervisão e conflitos:

```bash
python scripts/plan_workbook.py registros.json supervisao.json --mode new \
  --review-date 2026-10-21 --output plano-planilha.json
python scripts/plan_workbook.py registros.json supervisao.json --mode append \
  --existing planilha-recebida.xlsx --review-date 2026-10-21 --output plano-planilha.json
```

Usar a data real no fuso do usuário. Os nomes acima são intermediários privados.
O leitor reconhece o modelo de 23 ou 37 campos na primeira linha. Cabeçalho em
outra linha, nomes diferentes, colunas adicionais conflitantes ou aba renomeada
exigem mapeamento explícito antes da escrita. Não adivinhar por similaridade.
Linha antiga sem chave de fase e com mesmo CNJ bloqueia o acréscimo até identificar
a fase; não deduplicar todas as fases apenas pelo número do processo.
O contrato 2022 usa ID financeiro `4532022`, sem o rótulo territorial. O planejador
também reconhece a variante anterior `4532022RSSC` como a mesma chave; formatos
desconhecidos exigem reconciliação, sem autorizar repetição por diferença de grafia.
Reconhecer também os aliases legados de fase do contrato 2022: `DEFESA_IMPUGNACAO`
equivale a `DEFESA`, e `22_A/B/D` a `2022_22_A/B/D`, respectivamente. Preservar a
chave antiga na linha original; normalizar apenas para comparação.

Para executar o plano no ambiente Codex, usar a skill Spreadsheets e
`@oai/artifact-tool`. No site, integrar ao escritor XLSX do backend e preservar as
mesmas invariantes. Não usar os valores extraídos para substituir dados históricos:

1. Criar workbook novo ou importar a cópia completa. Validar macros, recursos não
   suportados, links e integridade antes de prometer preservação de arquivo complexo.
2. Preservar linhas existentes, formatação, validações, filtros, fórmulas, ordem de
   abas e cabeçalhos repetidos. Acrescentar controles X:AK apenas onde livres.
3. Escrever `append[].values` como valores literais em `excel_row`. Texto vindo de
   PDF ou usuário que começa com `=`, `+`, `-`, `@` não é fórmula. Usar API de célula
   de texto; fórmulas só quando geradas pelo escritor e baseadas em parâmetros confiáveis.
4. Converter datas ISO em datas de Excel e aplicar `dd/mm/yyyy`; manter CNJ como
   texto. Valor desconhecido é célula vazia, nunca zero. Tarifa é referência, mesmo
   se a linha estiver pendente. Não inventar preço de 2025.
5. Em nova planilha, criar REGRAS com os nove campos descritos abaixo. Em planilha
   existente, preservar REGRAS e sinalizar divergência de versão/valor antes de
   alterar parâmetros usados por fórmulas antigas; não atualizar preços em silêncio.
6. Acrescentar à aba `SUPERVISAO` os controles `supervision_rows`; validar seus
   cabeçalhos antes de reutilizar aba com esse nome. Registrar também cobertura por
   PDF, consumo e pendências do job em bloco identificado, sem nenhuma chave de API.
   A supervisão não duplica o histórico financeiro nem cria tabela de aprovação.
7. Guardar conflitos para resolução e não escrevê-los como novas cobranças. Se não
   houver linhas novas, ainda entregar relatório de cobertura/conflitos do lote.
8. Escrever uma vez por lote, sob lock; recalcular, verificar erros, comparar dados
   e fórmulas antigos e renderizar regiões alteradas. Salvar atomicamente outra
   versão/arquivo para download. Atualizar o registro de importação no mesmo commit
   lógico do resultado: falha entre gravação do XLSX e metadados não pode duplicar linhas.

Não enviar arquivo com fórmulas sobrescritas ou recursos removidos como se tivesse
sido preservado. Exportar relatório de conflito se a integração não conseguir
manter o modelo com segurança. Não marcar `ENCERRAR VIOS?` automaticamente.

## Aba REGRAS

Preservar título `Regras de enquadramento e remuneração` em A1:I1. Manter no quadro:
chave, contrato, tabela, procedimento, fase/hipótese, valor, autorização, condição e
fonte. Alimentar os valores a partir desse quadro. Acrescentar as decisões e
pendências abaixo. Manter números e datas tipados e fonte única dos parâmetros.
Não deixar `INDEX` converter tarifa vazia em zero. Conferir cada busca por controle
independente. Renderizar antes e depois de alterar o modelo.

## Dados para scripts/decidir_lote.py

Fornecer JSON com `records` (lista). Transpor o resultado intermediário para a
planilha junto às fontes. Nunca inventar confirmações para passar na validação.

| Campo JSON | Conteúdo |
|---|---|
| process, uf | CNJ e UF verificados |
| subs_date, subs_source | ISO AAAA-MM-DD e fonte específica SHR |
| shr_activity, shr_evidence | SIM/NAO/PENDENTE e lista de provas |
| absence_verified, review_complete | Confirmações documentadas da ausência |
| closure_date, extinction_date | Datas oficiais; closure_date somente baixa vigente |
| act_date, evidence | Data e lista das fontes da linha |
| tariff_key | Chave da tarifa; ausente quando não definida |
| responsible, billing_history | Responsável e SIM/NAO/PENDENTE para já faturado |
| single_pdf_checked, file_named_correctly | Booleanos de conferência |
| documentation_complete, qualification_confirmed | Booleanos de conferência |
| obligations_fulfilled | SIM, NAO_APLICAVEL ou PENDENTE |
| authorization_attached, authorization_prior, authorization_source | Documento e caráter prévio |
| bank_role | EXEQUENTE/EXECUTADO na ação |
| principal_bank_role, principal_role_evidence | Polo na relação principal, se incidente |
| payment_without_fine, payment_kind | Booleano e CONDENACAO/SUCUMBENCIA para 22-a |
| representation_replaced, ongoing_at_receipt | Booleanos necessários para 22-d |
| final_outcome_confirmed, notes_complete | Resultado final e notas relevantes conferidos |
| closure_cancelled, closure_without_success | Cancelamento conhecido e condição sem êxito das baixas 2020 |
| all_claims_dismissed, moral_damages_requested, moral_damages_excluded | Fatos específicos do bônus passivo, com fontes |
| agreement_homologation_date, defense_date, first_instance_decision_date | Datas ISO dos marcos do bônus por acordo |
| defense_not_filed_verified, first_decision_not_issued_verified, agreement_timing_source | Ausência do marco conferida e fonte cronológica, quando aplicável |
| analysis_phase | Fase informada para outras UFs |
| record_id, source_ids | ID estável da linha e SHAs dos PDFs vinculados, para supervisão |

Ausente significa não demonstrado. `NAO` em billing_history exige consulta interna.
Autorização anexada não prova que foi prévia: verificar data, escopo e fonte.
As confirmações humanas/financeiras exigem origem interna rastreável; não permitir
que uma resposta do modelo altere esses campos diretamente.
