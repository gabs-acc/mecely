# Mecely

Uma TUI para modelar *issue trees* de cases de consultoria e treinar
estimativas numéricas sem sair do terminal. Os atalhos são inspirados no
Vim, mas o app também funciona com o mouse e explica sozinho o que fazer.
Não é preciso saber Vim para usar.

## Recursos

- criação, edição e exclusão de ramos, editados na própria linha (sem
  pop-ups), com mouse ou teclado;
- navegação e seleção visual com atalhos inspirados no Vim;
- undo, redo, cópia e colagem de subárvores;
- operações algébricas entre nós irmãos, com cálculo automático de
  estimativas e aviso visual quando uma operação está faltando;
- um "entrevistador" de IA opcional para tirar dúvidas durante a resolução
  e avaliar a árvore inteira ao final, usando o CLI `claude`;
- documentos JSON explícitos, com salvamento manual por padrão;
- execução no terminal ou no navegador.

## Instalação

Requer Python 3.11 ou mais recente.

```bash
git clone https://github.com/gabs-acc/mecely.git
cd mecely
python -m venv .venv
source .venv/bin/activate
pip install -e .
mecely
```

Sem um caminho, o Mecely abre um buffer novo e não grava nada automaticamente.
Use `Ctrl+S` para escolher um nome JSON. Com um caminho posicional, o arquivo é
aberto se existir ou criado no primeiro salvamento.

## Comece por aqui: um tutorial guiado

Esta seção assume que você nunca abriu o Mecely. Ao final dela você terá
modelado e calculado um case simples de ponta a ponta. A qualquer momento,
pressione `?` para ver a lista completa de atalhos na tela.

### A tela inicial

Ao rodar `mecely` sem argumentos, você vê uma árvore com um único nó:

```
▾  Qual é a pergunta principal?
```

Acima da barra de atalhos, no rodapé, uma faixa colorida mostra `NORMAL`.
Esse é o *modo* atual. O Mecely tem três modos, como o Vim:

- **NORMAL**: navegar e disparar atalhos (o modo padrão);
- **INSERT**: digitando o texto ou o valor de um nó;
- **VISUAL**: selecionando vários nós de uma vez.

A faixa muda de cor e de nome conforme o modo muda, então você sempre sabe
onde está.

### Navegando pela árvore

- `j` / `k` (ou `↓` / `↑`) movem para o próximo nó / nó anterior;
- `h` (ou `←`) recolhe o ramo atual, ou vai para o pai se já estiver recolhido;
- `l` (ou `→`) expande o ramo atual, ou vai para o primeiro filho;
- `gg` (pressione `g` duas vezes) vai para o primeiro nó, `G` para o último;
- um clique do mouse também seleciona qualquer linha diretamente.

### Criando os primeiros ramos

Selecione a raiz e pressione `a` (adicionar filho). Isso já abre uma nova
linha em branco em modo **INSERT**, pronta para receber texto. Não existe
pop-up separado, você digita direto ali. Escreva algo como `Receita` e
pressione `Enter` para confirmar (ou `Esc` para cancelar e descartar a linha).

Com o novo nó ainda selecionado, pressione `o` (adicionar irmão) para criar
outro ramo no mesmo nível: digite `Custo` e confirme. Sua árvore agora é:

```
▾  Qual é a pergunta principal?
     Receita
     Custo
```

Para editar o texto de um nó já existente, selecione-o e pressione `i`
(ou dê um clique duplo nele com o mouse). O mesmo modo INSERT se abre,
agora pré-preenchido com o texto atual.

### Aprofundando a árvore

Repita `a` e `o` para quebrar `Receita` e `Custo` em partes menores. Por
exemplo, selecione `Receita`, pressione `a` para criar `Unidades vendidas`
como filho, depois `o` para criar `Preço/unidade` como irmão dele. Use `h`
para recolher um ramo grande e organizar a visão, `l` para expandi-lo de
novo.

### Atribuindo valores numéricos

Em uma folha (um nó sem filhos), pressione `=` para definir seu valor.
Também abre em INSERT, na própria linha, ao final do texto. Aceita números
simples, abreviações (`10k`, `2.5m`, `1b`), percentuais (`5%`) e até
expressões (`215m * 5% * 120`). Confirme com `Enter`.

Um nó com filhos nunca recebe valor diretamente: seu resultado é sempre
calculado a partir dos filhos, com base na operação entre eles.

### Combinando irmãos com uma operação

A partir do **segundo** filho de um nó (o primeiro sempre inicia a
expressão, sem operação), pressione `+`, `-`, `*` ou `/` para dizer como
ele se combina com o irmão anterior. `Backspace` limpa a operação de um nó.
Nenhum desses abre pop-up: o efeito é imediato.

Continuando o exemplo: em `Unidades vendidas`, defina `1000` com `=`; em
`Preço/unidade`, defina `50` com `=` e pressione `*` (multiplica pelo
irmão anterior). O resultado de `Receita` já aparece calculado:

```
▾  Qual é a pergunta principal?
   ▾  Receita  = 50k
        Unidades vendidas  = 1000
        [*] Preço/unidade  = 50
      Custo
```

Se um nó já tem um número pronto (valor ou resultado de filhos) mas ainda
não tem operação definida, ele aparece marcado com `[?]` em vez de ficar em
branco. Isso deixa claro que falta um passo, sem confundir com o primeiro
filho (que nunca precisa de operação). Em árvores puramente qualitativas,
sem nenhum valor, essa marca nunca aparece.

Repita o processo para `Custo` (com `Custo/unidade` e `Unidades vendidas`,
usando `-` na relação de `Custo` com `Receita`) até fechar a árvore
inteira. O resultado da raiz aparece automaticamente quando tudo estiver
completo.

### Corrigindo e reorganizando

- `u` desfaz a última alteração, `Ctrl+R` refaz;
- `x` (ou `Delete`) exclui o nó selecionado;
- `V` inicia a seleção visual (mova com `j`/`k` para estender), `y` copia a
  seleção ou subárvore, `p` cola depois do nó atual, `Esc` sai do visual.

### Praticando com um "entrevistador" de IA

Esses dois recursos são opcionais e exigem o CLI [`claude`](https://claude.com/claude-code)
instalado e configurado no seu `PATH`.

- `c` abre uma conversa com a IA no papel de entrevistador: pergunte por
  dados que o enunciado não deu, explique seu raciocínio, ou peça uma
  reação a uma recomendação. `Enter` envia a mensagem, `Alt+Enter` quebra
  linha (não `Shift+Enter`: a maioria dos terminais não distingue Shift+Enter
  de um Enter comum); `Esc` sai da digitação para rolar o histórico com
  `j`/`k`/`Ctrl+D`/`Ctrl+U`/`PgUp`/`PgDn`, `i` volta a digitar, `Esc` de novo
  fecha a tela.
- `!` avalia a árvore inteira contra uma rubrica (estrutura MECE,
  adequação da técnica, insight, rigor quantitativo e clareza). Pede
  confirmação antes de rodar. Na tela de resultado, `y` copia o texto,
  `?`/`Esc`/`q` fecha.

### Biblioteca de cases (experimental)

`R` abre uma tela para escolher um case de uma biblioteca local,
substituindo a árvore atual (`u` desfaz). A lista agrupa os cases por
casebook, mostrando o nome do livro uma vez por seção em vez de repeti-lo
em cada linha. Um campo de texto filtra por título, tipo, dificuldade ou
casebook: cada palavra digitada precisa aparecer em algum desses campos
(em qualquer ordem, não precisam estar juntas), e uma palavra pode ser
restrita a um campo específico com `campo:valor`, por exemplo
`dificuldade:difícil tipo:mercado`; os prefixos aceitos são `titulo:`,
`tipo:`, `dificuldade:` e `livro:` (ou `casebook:`). `Ctrl+R` só destaca
um case aleatório dentre os que passam no filtro atual (ou dentre todos,
sem filtro), sem escolher, então dá pra sortear de novo, navegar
manualmente pra trocar o destacado, ou confirmar com `Enter`;
`Ctrl+D`/`Ctrl+U`/`PgUp`/`PgDn` rolam a lista, os mesmos atalhos do chat
com a IA; `Esc` cancela.

Ao carregar um case, a tela do enunciado abre sozinha, mostrando só o
texto do problema (sem abordagem sugerida, cálculos ou recomendação);
`E` reabre essa tela a qualquer momento durante a resolução, `y` copia
o texto, `Esc`/`q` fecha.

Esse recurso lê de um arquivo `.json`: uma lista de objetos com, no
mínimo, `id`, `book`, `title`, `type`, `difficulty` e `texto_completo`
(o texto integral do case, incluindo eventual gabarito). Um campo
`enunciado` opcional guarda a versão limpa, sem gabarito, que é a
mostrada ao candidato; sem ele, a tela cai de volta pro título e
metadados do case. O Mecely não inclui nem gera esse arquivo: monte a
biblioteca você mesmo, a partir de material que você tem o direito de
usar, e mantenha o arquivo fora deste repositório, já que o conteúdo
de casebooks costuma ter direitos autorais de terceiros.

O caminho normalmente vem de `cases.file` no `config.toml`. Se não
houver nada configurado, pressionar `R` pede o caminho na hora, só para
aquela execução: nada é salvo em disco, e da próxima vez que abrir o
Mecely a pergunta volta a aparecer, a menos que você configure
`cases.file` para deixar de vez.

Quando um case da biblioteca está carregado, o entrevistador de IA (`c`)
e a avaliação (`!`) mudam de comportamento: em vez de poder improvisar
dados plausíveis para o que o enunciado não cobre, a IA é instruída a
citar só fatos literalmente presentes no texto do case, e a dizer que a
informação não está disponível quando não for o caso. É uma fidelidade
estrita à fonte, já que agora existe uma fonte real por trás do case.

### Salvando e saindo

`Ctrl+S` salva. Se o buffer ainda não está associado a um arquivo, pede um
nome `.json`. `q` sai do Mecely.

Isso cobre o essencial. A referência abaixo lista todos os atalhos, para
consulta rápida depois que a rotina virar hábito.

## Referência de atalhos

| Tecla | Ação |
|---|---|
| `j` / `k` (ou `↓` / `↑`) | mover para o próximo nó / nó anterior |
| `h` (ou `←`) | recolher ramo ou selecionar o pai |
| `l` (ou `→`) | expandir ramo ou selecionar o primeiro filho |
| `gg` / `G` | primeiro / último nó |
| clique | selecionar nó com o mouse |
| clique duplo | editar nó com o mouse |
| `a` (ou `Tab`) | adicionar nó filho (INSERT) |
| `o` (ou `Enter`) | adicionar nó irmão (INSERT) |
| `i` | editar texto do nó (INSERT) |
| `=` | definir valor ou expressão numérica (INSERT) |
| `Enter` | confirmar (sair do INSERT) |
| `Esc` | cancelar (sair do INSERT) |
| `x` (ou `Delete`) | excluir nó |
| `+` `-` `*` `/` | definir operação com o irmão anterior |
| `Backspace` | limpar a operação do nó |
| `c` | conversar com a IA |
| `!` | avaliar o case com IA |
| `R` | sortear/escolher case de uma biblioteca local |
| `E` | reler o enunciado do case carregado |
| `u` / `Ctrl+R` | desfazer / refazer |
| `V` | iniciar ou encerrar seleção visual |
| `y` / `p` | copiar / colar subárvore |
| `Ctrl+S` | salvar |
| `q` | sair |
| `?` | abrir ou fechar a ajuda |

## Linha de comando

```text
mecely [arquivo] [opções]
```

```bash
mecely                                          # buffer novo, sem arquivo
mecely estimativa.json --new --title "Case"     # árvore nova associada a um arquivo
mecely cases/lucratividade.json                 # trabalhar em um arquivo específico
mecely entrevista.json --read-only              # abrir sem permitir gravação
mecely --new --prompt "Enunciado do case..."    # árvore nova com enunciado (usado na avaliação por IA)

mecely --help
mecely --version
```

### Navegador

```bash
pip install -e '.[web]'
mecely --web
```

Abre `http://localhost:8000` (endereço e porta configuráveis com `--host`/`--port`).
O servidor é local por padrão; não exponha em rede não confiável sem autenticação.

## Configuração

Preferências ficam fora da aplicação, em `~/.config/mecely/config.toml`
(respeitando `XDG_CONFIG_HOME`, ou um caminho escolhido com `--config`).
Use [`config.example.toml`](config.example.toml) como base: ele traz a
paleta de cores completa, autosave, configuração do servidor web e o
arquivo da biblioteca de cases (veja "Biblioteca de cases" acima).

## Testes

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Princípio de uso

O Mecely organiza e torna visível o raciocínio do candidato. Ele não foi
projetado para fornecer respostas ocultas ou assistência incompatível com as
regras de um processo seletivo.

## Licença

MIT.
