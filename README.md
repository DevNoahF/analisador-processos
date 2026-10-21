# Supervisora documental Banrisul SHR

Dashboard para organizar lotes de PDFs, registrar fatos com fontes, conferir páginas, executar revisão por Gemini/Claude/OpenAI API e preparar a planilha FORÇA TAREFA 2. Uma senha compartilhada dá acesso ao workspace, aos uploads e aos resultados de todas as pessoas que entram na mesma instância. O arquivo com o hash da senha e os dados fica no diretório `data/`, excluído do Git.

O servidor local escuta somente em `127.0.0.1`; o dashboard não fica acessível remotamente até ser implantado em um servidor. No primeiro acesso, crie uma senha compartilhada para o workspace. Para a equipe entrar remotamente, use o [guia de hospedagem HTTPS](DEPLOY.md) e configure a mesma senha no servidor. Use a revisão por API somente depois de carregar documentos que realmente deseja enviar ao provedor escolhido. A chave é apagada da memória ao terminar a etapa; não é salva em arquivo. O catálogo configurado já oferece modelos atuais da OpenAI, Anthropic e Gemini; confirme que sua conta tem acesso ao modelo escolhido.

## Executar

```bash
./run.sh
```

Na primeira execução, o script cria `.venv` e instala as dependências. Depois, abra `http://127.0.0.1:8765`. Para escolher outra porta, use `SHR_PORT=9000 ./run.sh`.

O seletor lê `SHR_MODELS_JSON` do arquivo privado `.env` ou do ambiente do servidor. Os IDs configurados e confirmados nas documentações atuais são:

```bash
{"openai":["gpt-6.1-sol","gpt-6-luna","gpt-6-astra"],"anthropic":["claude-sonnet-5-5","claude-haiku-5-5","claude-opus-5-5","claude-fable-5-1"],"gemini":["gemini-3.8-flash"]}
```

Os nomes acima são exemplos estruturais. Use os IDs vigentes aprovados para sua conta. O código não procura automaticamente modelos nem muda de provedor. Nenhuma chamada de API acontece sem você iniciar a revisão e informar sua chave na tela.

## Trabalhar com um lote

1. Crie um lote, escolha criação de uma planilha nova ou acréscimo à original e envie PDFs. Para acréscimo, inclua também a planilha XLSX original.
2. Clique em **Extrair e preparar análise**. A capa preenche somente a triagem inicial; revise o CNJ/UF. A extração local inventaria as páginas e **não executa OCR**.
3. Abra cada página alertada, confira sua imagem e confirme a leitura, registrando responsável/data e o conteúdo final conferido. Isso é uma autodeclaração do usuário, não uma verificação visual independente do servidor.
4. Edite os registros com o Subs específico da SHR, atos, datas, histórico consultado e fontes. A lista de hipóteses é uma referência; cada item ainda exige comprovação contratual. Dados internos sem acesso permanecem pendentes.
5. Confira o pré-voo de páginas e orçamento. Escolha provedor e modelo homologado, cole a chave e inicie a revisão. O texto extraído vai ao serviço escolhido. Revise cada pendência antes de exportar.
6. Gere o XLSX e relatório JSON. O exportador preserva as linhas existentes, bloqueia fases conflitantes e mantém `ENCERRAR VIOS?` pendente.

A exportação local sem API é uma preparação preliminar com status `PENDENTE`; o relatório identifica ausência de revisão. Um XLSX com funcionalidades complexas e não suportadas é recusado com segurança; nesses casos, crie uma planilha nova.

## Testes

A suíte do núcleo documental continua em `.codex/scripts`. Testes adicionais de integração usam um PDF sintético e respostas simuladas; não fazem chamadas pagas nem avaliam processos reais.

```bash
.venv/bin/python -m unittest discover -s .codex/scripts -p 'test_*.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

Confira regras, contratos e limitações no diretório `.codex/` antes de usar dados reais. Este dashboard local não inclui autenticação organizacional, banco multiusuário, hospedagem online ou serviço de OCR.
# analisador-processos
