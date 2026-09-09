# Mecely

Uma TUI Vim-first para modelar *issue trees* e estimativas numéricas sem sair
do terminal.

## Recursos

- criação, edição, exclusão e recolhimento de ramos;
- navegação e seleção visual com atalhos inspirados no Vim;
- undo, redo, cópia e colagem de subárvores;
- operações algébricas entre nós irmãos e cálculo automático de estimativas;
- documentos JSON explícitos, com salvamento manual por padrão;
- execução no terminal ou no navegador.

## Executar

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

## Linha de comando

```text
mecely [arquivo] [opções]
```

```bash
mecely                                          # buffer novo, sem arquivo
mecely estimativa.json --new --title "Case"     # árvore nova associada a um arquivo
mecely cases/lucratividade.json                 # trabalhar em um arquivo específico
mecely entrevista.json --read-only              # abrir sem permitir gravação

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
Use [`config.example.toml`](config.example.toml) como base — ele traz a
paleta de cores completa, autosave e configuração do servidor web.

## Atalhos Vim

| Tecla | Ação |
|---|---|
| `J` / `K` | selecionar próximo nó / nó anterior |
| `H` | recolher ramo ou selecionar o pai |
| `L` | expandir ramo ou selecionar o primeiro filho |
| `A` | criar nó filho |
| `O` | criar nó irmão |
| `I` | editar nó |
| `X` | excluir nó |
| `=` | definir valor de uma folha |
| `+` `-` `*` `/` | definir operação com o irmão anterior |
| `Backspace` | limpar a operação do nó |
| `U` | desfazer alteração |
| `Ctrl+R` | refazer alteração |
| `V` | iniciar ou encerrar seleção visual |
| `Y` | copiar a seleção ou subárvore |
| `P` | colar depois do nó atual |
| `g` / `G` | primeiro / último nó |
| `Ctrl+S` | salvar |
| `Q` | sair |
| `?` | abrir ou fechar a ajuda |

Setas, `Tab`, `Enter` e `Delete` funcionam como alternativas.

## Estimativas numéricas na árvore

Em uma folha, pressione `=` para informar o valor. Em cada filho a
partir do segundo, pressione `+`, `-`, `*` ou `/` para definir a operação com
o irmão anterior (`Backspace` limpa). O primeiro filho inicia a expressão.

```text
Lucro = 20k
├─ Receita = 50k
│  ├─ Unidades vendidas = 1k
│  └─ [*] Preço/unidade = 50
└─ [-] Custo = 30k
   ├─ Custo/unidade = 30
   └─ [*] Unidades vendidas = 1k
```

Valores aceitam expressões, percentuais e abreviações `k`, `m` e `b`.

Veja em ação:

[![asciicast](https://asciinema.org/a/1263261.svg)](https://asciinema.org/a/1263261)

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
