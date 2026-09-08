"""Builds the prompt sent to an external AI (via the `claude` CLI) to
evaluate a case tree against Mecely's rubric.

This module only builds text — it never calls a subprocess itself, so it
stays trivially testable. The actual `claude -p` call lives in app.py's
`action_evaluate`, since that needs the Textual event loop.
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

B. Adequação da técnica ao problema — a relação usada entre irmãos (soma, \
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
        relation = f"[{node.relation}] " if node.relation else ""
        value = f" = {result}" if result is not None else ""
        lines.append(f"{'  ' * depth}- {relation}{node.text}{value}")
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
