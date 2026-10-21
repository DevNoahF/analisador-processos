---
name: banrisul-process-analyzer
description: Analisar lotes de PDFs Banrisul SHR e implementar supervisão documental em site com chave de API do próprio usuário, escolhendo Gemini, Claude ou ChatGPT/OpenAI. Revisar todas as páginas, análise inicial e regras com orçamento, cache, retomada e citações verificáveis. Acrescentar lançamentos à planilha recebida ou criar XLSX pelo modelo FORÇA TAREFA 2 e REGRAS. Aplicar contratos 1700165/2020, 453/2022 RS-SC e 2025, Subs, atuação SHR, baixa, 22-k, bônus e não cumulatividade, sem liberar faturamento automaticamente.
---

# Analisador e supervisora Banrisul SHR

Reproduzir o procedimento de extração, enquadramento e preenchimento da força-tarefa.
Produzir lançamentos rastreáveis. Manter **PENDENTE** toda conclusão sem os dados
necessários. Distinguir candidato a remuneração de cobrança liberada.

## Escolher o modo de execução

- Para análise local, seguir a sequência documental abaixo; não exigir chave de API
  só para extrair PDFs, aplicar regras ou preparar a planilha.
- Para criar/alterar o fluxo do site com supervisão por API, ler primeiro
  [supervisao-site.md](references/supervisao-site.md) e
  [providers.md](references/providers.md). Implementar seleção de provedor, chave
  privada por usuário/job, processamento em lote e os dois modos de planilha.
  Não afirmar que um site foi modificado quando apenas a skill foi entregue.
- Em revisão por API iniciada pelo usuário, revisar todos os PDFs e todo o texto das
  páginas; manter pendências de OCR/imagens separadas da cobertura textual. Não
  substituir isso por amostra nem aprovar o restante por economia de tokens.
- Usar `scripts/providers.py` e `scripts/supervisao.py` como núcleo de integração
  ao backend autenticado. Não expor credencial no frontend após o envio, arquivos,
  prompts ou logs. Não solicitar chaves em conversa.
- Manter a decisão tarifária em `decidir_lote.py`. A supervisora detecta divergências
  sem reescrever regras, criar prova ou marcar cobrança/VIOS como concluídos.

O pacote não é um site pronto: autenticação, armazenamento privado, fila e escritor
XLSX são integrados ao produto existente seguindo os contratos das referências.

## Preparar as fontes

1. Ler os PDFs processuais, a planilha atual, a tabela contratual e as orientações do
   usuário. Não confiar apenas no histórico da conversa ou no nome do arquivo.
2. Reutilizar cópias locais fornecidas. Para arquivos apenas na Library, usar a skill
   correspondente; preservar identidade e versões ao editar a planilha.
3. Ler [contratos.md](references/contratos.md), [planilha.md](references/planilha.md)
   e [extracao.md](references/extracao.md).
4. Confrontar [tarifas.json](references/tarifas.json) com as fontes atuais. Essa
   fotografia reproduz a aba REGRAS de 21/10/2026, sem dados dos processos. Priorizar
   orientações explícitas atuais e registrar divergências, sem presumir reajustes.
5. Carregar as skills de PDF e planilhas disponíveis. Para escrever XLSX neste
   ambiente, seguir a skill de planilhas e usar `@oai/artifact-tool`.

Não solicitar novamente um arquivo disponível. Não interromper todo o lote por uma
pendência individual: preencher o comprovado e especificar o que falta.

## Executar nesta ordem

### 1. Identificar e verificar a leitura

- Obter CNJ, UF, classe, vara, partes e polo do banco da capa oficial do eproc.
- Comparar capa, separadores, rodapés e CNJ esperado na planilha. Separar principal,
  originário, cumprimento e recursos. Não substituir o CNJ de linha existente pelo
  de processo relacionado sem explicar a relação e preservar o registro.
- Sinalizar nome de PDF divergente da capa. Não obter UF de endereço ou cabeçalho de
  petição, pois podem conter erros de modelo.
- Separar eventos por `PÁGINA DE SEPARAÇÃO`; capturar número, descrição, data/hora,
  usuário e processo. Associar peças por processo + evento + código do documento.
- Decodificar entidades HTML, incluindo `APELA&Ccedil;&Atilde;O1`.
- Verificar o texto do **corpo**, retirando o rodapé automático. Detectar páginas
  digitalizadas, imagens relevantes e caracteres corrompidos. Fazer OCR local ou
  registrar a leitura pendente; texto extraível não comprova leitura integral.
- Executar `scripts/extract_eproc.py` para inventário e alertas. Não tratá-los como
  decisão de faturamento nem como prova de ausência de atuação.

### 2. Comprovar atuação e Subs

- Localizar peças efetivamente apresentadas pela SHR, com autoria/assinatura e
  protocolo. Não confundir intimação, cadastro de procurador, nome transcrito ou
  documento de outro escritório com atuação.
- Registrar documento, evento, páginas e data. Distinguir signatário da peça do
  **advogado responsável interno**, que pode não estar informado.
- Usar `Sim`, `Não` e `Pendente`. Usar `Não` somente após verificação suficiente da
  ausência. Busca textual negativa ou PDF parcialmente ilegível = `Pendente`.
- Identificar o Subs específico destinado à SHR e ao processo correto. Reconhecer
  também `S U B S T A B E L E C I M E N T O`. Distinguir data do documento,
  juntada, procuração originária, primeiro ato e tombamento interno.
- Consultar a rede indicada pelo usuário quando houver acesso autorizado. Sem
  acesso ou documento, registrar a limitação e deixar a data faltante em branco.
  Não usar Subs de outro escritório nem inventar datas.

### 3. Escolher contrato antes da tabela e do valor

| Entrada | Contrato |
|---|---|
| RS ou SC, qualquer data de Subs | 453/2022 (RS-SC), fase 2 |
| Demais UFs, Subs até 22/12/2025 | 1700165/2020 |
| Demais UFs, Subs desde 23/12/2025 | 2025 |
| Demais UFs, ano 2026 do CNJ | 2025 |
| Dados insuficientes | PENDENTE SUBS / UF |

Aplicar primeiro a exceção territorial RS/SC, inclusive se surgir CNJ de 2026, e
explicitar essa precedência. Não tratar uma petição em 2026 como processo de 2026.
Não supor fase 1 para as demais UFs: a fase 2 também pode incluir outros contratos.

### 4. Reconstruir extinção e baixa

- Percorrer a cronologia do processo correto. Distinguir baixa definitiva,
  arquivamento administrativo, suspensão, baixa de recurso e reativação/cancelamento.
- Desconsiderar baixa cancelada e procurar nova baixa vigente, citando os eventos.
  Não encerrar execução em andamento porque um agravo foi baixado.
- Separar datas de extinção, baixa e cumprimento das obrigações. Baixa sozinha não
  comprova custas, condenação ou sucumbência satisfeitas.
- Sem atuação confirmada e baixa **antes** do Subs: análise 22-k, R$ 50,00,
  sujeita à autorização prévia expressa indicada na regra.
- Sem atuação confirmada e baixa **depois** do Subs: encerramento na tabela do
  contrato, procedimento e polo aplicáveis.
- Data ausente, igualdade de datas ou extinção antes do Subs com baixa depois:
  manter a decisão pendente e explicar a ambiguidade. Não criar regra para igualdade.

### 5. Identificar atos ou fases remuneráveis

- Ler o conteúdo; `PET1`, `SENT1` ou `CONTRAZ1` apenas localizam a peça.
- Gerar uma linha para cada ato ou fase **contratualmente remunerável**, incluindo
  candidatos com enquadramento pendente quando houver evidência concreta.
- Agrupar várias petições da mesma fase em um lançamento. Na tabela 2022, remunerar
  uma fase por processo, ressalvadas exceções expressas como notas (2) e (3) de
  audiências. Não aplicar “uma petição, uma cobrança”.
- Consultar histórico financeiro. Vazio não significa não faturado. Construir chave
  por CNJ + contrato + fase/grupo de exclusão, sem usar evento para disfarçar repetição.
- Não cobrar atos anteriores de outro escritório nem retroagir remuneração.
- Conferir resultado final e acórdão antes de bônus. Não usar só a sentença se houve
  recurso. Exigir pedido e afastamento efetivos para bônus de dano moral.
- Aplicar exclusões de [contratos.md](references/contratos.md); não escolher apenas
  o maior valor. Encaminhar bônus ativo 2020/tabela 27 à coordenação.
- Não aplicar tabela 10 de 2022 ao banco executado só pela classe do cumprimento.
  Exigir banco exequente na relação principal ou contexto correspondente comprovado.
  Sem tabela para cumprimento passivo, deixar o valor em branco.
- Para 22-a, exigir condenação/sucumbência paga sem multa. Não confundir com custas
  nem bloqueio acrescido de multa. Para 22-d, comprovar substituição de representação,
  processo em andamento e autorização; mera procuração não basta.
- Não lançar recurso autônomo só por comunicação de distribuição. Obter peça e
  protocolo no processo do recurso.

### 6. Preencher FORÇA TAREFA 2 e REGRAS

- Permitir escolher **acrescentar à planilha enviada** ou **criar do zero** pelo
  esquema `assets/workbook-schema.json`, que reproduz os campos do modelo recebido
  sem dados dos processos. Não exigir XLSX prévio no modo de criação.
- Mapear a planilha atual conforme [planilha.md](references/planilha.md). Preservar
  os 23 campos originais e os controles adicionais; não apagar histórico.
- Planejar com `scripts/plan_workbook.py`. Em acréscimo, preservar linhas, valores,
  fórmulas e confirmações anteriores; conflitos pela chave da fase entram em fila
  de reconciliação. CNJ igual pode ter outra fase legítima. Nunca substituir linha
  já faturada nem interpretar campo vazio como liberação para duplicar.
- Preencher fatos, tarifa de referência e evidências. Deixar preço desconhecido em
  branco e explicar. Não transformar ausência em zero nem inventar tarifas de 2025.
- Manter REGRAS com chave, contrato, tabela, procedimento, hipótese, valor,
  autorização, condição e fonte, além das regras de decisão e pendências.
- Citar PDF, evento, código e páginas físicas. Distinguir páginas internas da peça.
- Usar datas tipadas, números e fórmulas auditáveis. Preservar cabeçalho verde,
  abas, formatação e os cabeçalhos repetidos da planilha recebida.
- Usar chaves de tarifa com letras, números e `_`, sem `|`. Comparar cada busca por
  `INDEX/MATCH` com a tabela: uma fórmula sem erro pode retornar tarifa errada.
- Permitir `APTO À CONFERÊNCIA FINAL` só com todos os requisitos comprovados.
  Usar `JÁ FATURADO` somente com histórico. Não marcar “faturado” nem encerrar VIOS
  automaticamente por ter encontrado uma peça.

Executar `scripts/decidir_lote.py` para conferir os fatos estruturados e duplicidades.
O script não lê documentos, não prova ausência de atuação e não autoriza cobrança.
Não preencher confirmações como verdadeiras apenas para passar na validação.

### 7. Verificar e entregar

1. Conferir tarifas, fontes, grupos de exclusão e requisitos por lançamento.
   Quando a supervisão por API estiver habilitada, concluir revisão das páginas e
   revisão cruzada, validar JSON/citações e manter cada falha como pendência.
2. Testar cortes 22/12 e 23/12/2025, RS/SC, CNJ 2026, Subs ausente, antes/depois,
   igualdade, extinção versus baixa e duplicidade, usando os testes do pacote.
3. Recalcular a planilha, procurar erros e comparar com controles independentes.
   Restaurar os dados usados nos testes.
4. Renderizar as regiões alteradas e conferir legibilidade e preservação do modelo.
5. Salvar a planilha com identidade e versões preservadas e entregar o arquivo.
6. Informar quantidade de lançamentos, caráter preliminar e pendências concretas.
   No site, mostrar também cobertura por PDF/página, provedor/modelo, consumo real,
   reserva estimada, achados e opção de retomar. Não prometer erro zero.

## Verificar alterações deste pacote

Executar `python -m unittest discover -s scripts -p 'test_*.py'`. Os testes de API
usam transportes simulados e não consomem chave nem tokens pagos. Homologar os
modelos efetivamente oferecidos pelo site antes de usar em produção. Não apresentar
teste simulado como chamada real aos provedores.

Não fixar nove lançamentos, quatro processos ou um conjunto de nomes: essas
quantidades pertencem ao lote de origem, não a uma regra geral.
