"""Builds the prompt sent to an external AI (via the `claude` CLI) to
evaluate a case tree against Mecely's rubric.

This module only builds text — it never calls a subprocess itself, so it
stays trivially testable. The actual `claude -p` call lives in app.py's
`action_evaluate`, since that needs the Textual event loop.

Note on data fidelity: `tree.prompt` today is a short, user-authored
paragraph, so the "interviewer" is expected to improvise plausible data
beyond it. Once real sourced cases (with their full exhibits/data
tables) are wired in, the interviewer should switch to strict fidelity —
never inventing facts the source case doesn't provide. That needs the
full case text available to the prompt, not just the one-paragraph
`prompt` field, so it isn't handled here yet.
"""

from __future__ import annotations

from .model import IssueTree, Node

RUBRIC = """\
Você está avaliando a resposta de um candidato a um case de consultoria, \
estruturada como uma árvore de decomposição (issue tree). Avalie usando \
estes cinco critérios, nesta ordem:

A. Conformidade MECE — os ramos de um mesmo nó cobrem coisas realmente \
distintas (sem overlap) e, juntos, esgotam razoavelmente o que compõe o \
nó pai (sem gaps)? Isso é mais crítico na primeira camada da árvore.

B. Adequação da técnica ao problema — a operação usada entre irmãos (soma, \
subtração, multiplicação, divisão) ou a lógica do agrupamento fazem \
sentido para o tipo de pergunta? Estruturas puramente matemáticas servem \
bem a métricas quantificáveis; problemas qualitativos/estratégicos pedem \
categorias conceituais ou processo, não uma fórmula forçada.

C. Insight e priorização — a primeira camada revela a característica \
fundamental do problema, ou só categoriza superficialmente? A estrutura \
foi adaptada ao case específico, ou é um framework genérico encaixado à \
força? Se houver uma recomendação final (nas anotações), ela reconhece \
um trade-off ou efeito de segunda ordem, em vez de só declarar uma \
conclusão? Uma boa recomendação costuma ter: afirmação da solução, \
razões, riscos, próximos passos, e reafirmação da solução.

D. Rigor quantitativo — a árvore fecha matematicamente (nenhum ramo \
incompleto)? Os valores são plausíveis? Aumentar ou diminuir um ramo \
realmente move a métrica-alvo na direção esperada, ou o candidato incluiu \
um fator que não é causa real do problema?

E. Clareza e eficiência — os nomes dos nós são específicos ao case, não \
genéricos? Nenhuma técnica é repetida à toa quando uma mais forte já \
bastaria? Lida em voz alta camada por camada, a árvore soa como uma \
explicação coerente?

Formato da resposta: para cada critério (A-E), dê um veredito objetivo \
seguido de uma explicação específica, citando textos e valores reais da \
árvore abaixo — não um comentário genérico que serviria para qualquer \
case. Entre ser sucinto e ser informativo, priorize ser informativo: \
explique o porquê e dê exemplos concretos. Termine com uma síntese \
apontando as 1-2 prioridades de melhoria mais importantes, não uma nota \
numérica agregada.
"""


def render_tree(tree: IssueTree) -> str:
    lines: list[str] = []

    def visit(node: Node, depth: int) -> None:
        result = node.result()
        operation = f"[{node.operation}] " if node.operation else ""
        value = f" = {result}" if result is not None else ""
        lines.append(f"{'  ' * depth}- {operation}{node.text}{value}")
        for child in node.children:
            visit(child, depth + 1)

    visit(tree.root, 0)
    return "\n".join(lines)


def build_prompt(tree: IssueTree) -> str:
    parts = [RUBRIC, "\n---\n"]
    if tree.prompt:
        parts.append(f"Enunciado do case:\n{tree.prompt}\n")
    parts.append(f"Árvore do candidato:\n{render_tree(tree)}\n")
    if tree.notes:
        notes_lines = "\n".join(f"[{note.author}] {note.text}" for note in tree.notes)
        parts.append(f"Anotações e diálogo durante a resolução:\n{notes_lines}\n")
    return "\n".join(parts)


NOTE_REPLY_INSTRUCTIONS = """\
Você está atuando como o entrevistador de um case de consultoria. O \
candidato está resolvendo o case abaixo e acabou de escrever uma \
anotação — pode ser uma pergunta, uma explicação, ou parte de uma \
recomendação. Responda apenas à anotação MAIS RECENTE (a última da lista \
abaixo).

Siga à risca as informações que o enunciado do case já dá. Se ele não \
especifica um dado que o candidato está pedindo, você tem três opções — \
escolha a mais apropriada para aquele momento da entrevista, como um \
entrevistador real escolheria:
1. Fornecer um valor específico e plausível, mantendo consistência com \
qualquer dado que você já tenha dado antes nesta mesma conversa — use \
isso quando o dado não é o ponto central a ser testado.
2. Se for um valor numérico que faz mais sentido o próprio candidato \
estimar (ex.: tamanho de mercado, uma métrica que exige raciocínio, não \
só lembrar um fato), devolva pedindo que ele estime, em vez de entregar \
o número — isso também é comportamento realista de entrevistador.
3. Se a pergunta for sobre algo irrelevante para o case ou que não faz \
sentido ter resposta, pode dizer que essa informação não está disponível \
ou não é relevante, sem inventar nada.

Nunca responda a uma pergunta de dado devolvendo outra pergunta sobre \
metodologia ou pedindo que o candidato justifique antes de responder — \
isso não é comportamento de entrevistador, é comportamento de coach.

O único tipo de informação que você NÃO revela nunca é a análise, a \
causa-raiz ou a recomendação do case — isso o candidato tem que \
descobrir sozinho.

Se a anotação for uma explicação ou parte de uma recomendação (não uma \
pergunta de dado), reaja brevemente como um entrevistador reagiria: pode \
confirmar, apontar uma lacuna específica, ou deixar o candidato seguir \
em frente — sem entregar a resposta do case.

Responda em 1 a 3 frases, direto ao ponto.
"""


def build_note_reply_prompt(tree: IssueTree) -> str:
    parts = [NOTE_REPLY_INSTRUCTIONS, "\n---\n"]
    if tree.prompt:
        parts.append(f"Enunciado do case:\n{tree.prompt}\n")
    parts.append(f"Árvore atual do candidato:\n{render_tree(tree)}\n")
    notes_lines = "\n".join(f"[{note.author}] {note.text}" for note in tree.notes)
    parts.append(f"Anotações (a última é a mais recente):\n{notes_lines}\n")
    return "\n".join(parts)
