"""As ferramentas que o agente pode chamar.

Uma "tool" é uma função Python normal que o LLM decide invocar. O modelo
NÃO vê o corpo da função -- ele vê apenas o nome, a assinatura e a
DOCSTRING. Por isso a docstring é o contrato: ela é o manual de instruções
que o modelo lê para decidir quando e como usar cada ferramenta.
"""

from __future__ import annotations

# ast = "abstract syntax tree": lê código Python como estrutura, sem executá-lo
import ast
import logging
# Any é usado só na anotação do nó da árvore, que pode ser de vários tipos
from typing import Any

# O decorador que transforma uma função comum em ferramenta utilizável pelo LLM
from langchain_core.tools import tool

from rag_agent.store import search

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- busca
# @tool lê a assinatura e a docstring da função e monta o schema que vai no prompt
@tool
def buscar_documentacao(pergunta: str) -> str:
    """Busca trechos relevantes na documentação interna do produto Nimbus.

    Use SEMPRE que a pergunta envolver preços, planos, limites técnicos,
    instalação, configuração ou cancelamento. Não responda sobre esses
    assuntos de memória: consulte aqui primeiro.

    Args:
        pergunta: a pergunta em linguagem natural, com as palavras do usuário.

    Returns:
        Os trechos encontrados, cada um com o nome do arquivo de origem.
    """
    # search devolve pares (documento, distância); distância menor = mais parecido
    resultados = search(pergunta)

    # Nenhum resultado: devolver texto explicativo, NUNCA levantar exceção.
    # O modelo lê essa string e sabe que precisa dizer "não encontrei"
    if not resultados:
        return "Nenhum trecho relevante encontrado na documentação."

    partes: list[str] = []
    # enumerate(..., 1) numera os trechos a partir de 1, pra ficar legível no prompt
    for i, (doc, distancia) in enumerate(resultados, start=1):
        # .get() com padrão evita KeyError se algum documento vier sem 'source'
        fonte = doc.metadata.get("source", "desconhecida")
        # O rótulo [fonte: X] é o que permite o modelo CITAR de onde tirou a resposta
        partes.append(f"--- Trecho {i} [fonte: {fonte} | distância {distancia:.3f}]\n{doc.page_content}")

    logger.info("buscar_documentacao(%r) -> %d trechos", pergunta, len(resultados))
    # Junta tudo num texto só, porque a ferramenta precisa devolver string pro modelo
    return "\n\n".join(partes)


# ----------------------------------------------------------- calculadora
# Só estes nós de sintaxe são aceitos. Qualquer outro (chamada de função,
# import, atributo) é recusado -- é o que impede execução de código arbitrário
_NOS_PERMITIDOS = (
    ast.Expression,  # a expressão inteira
    ast.BinOp,       # operação com 2 lados: 2 + 3
    ast.UnaryOp,     # operação com 1 lado: -5
    ast.Constant,    # um número literal
    ast.Add, ast.Sub, ast.Mult, ast.Div,      # + - * /
    ast.Pow, ast.Mod, ast.FloorDiv,           # ** % //
    ast.USub, ast.UAdd,                       # -x  +x
)


def _avaliar_seguro(no: Any) -> float:
    """Percorre a árvore da expressão e recusa qualquer nó fora da lista branca."""
    # isinstance verifica se o nó é de um dos tipos permitidos
    if not isinstance(no, _NOS_PERMITIDOS):
        # __class__.__name__ dá o nome do tipo do nó, pra mensagem de erro útil
        msg = f"Elemento não permitido na expressão: {no.__class__.__name__}"
        raise ValueError(msg)

    # ast.Expression é a casca externa; o conteúdo fica em .body
    if isinstance(no, ast.Expression):
        return _avaliar_seguro(no.body)

    # Constant é um valor literal; só aceitamos números (não strings, não None)
    if isinstance(no, ast.Constant):
        if not isinstance(no.value, (int, float)):
            msg = "Só números são aceitos."
            raise ValueError(msg)
        return float(no.value)

    # UnaryOp = um operador na frente de um valor: -5, +3
    if isinstance(no, ast.UnaryOp):
        valor = _avaliar_seguro(no.operand)
        return -valor if isinstance(no.op, ast.USub) else valor

    # BinOp = valor operador valor. Resolve os dois lados recursivamente
    esquerda = _avaliar_seguro(no.left)
    direita = _avaliar_seguro(no.right)

    if isinstance(no.op, ast.Add):
        return esquerda + direita
    if isinstance(no.op, ast.Sub):
        return esquerda - direita
    if isinstance(no.op, ast.Mult):
        return esquerda * direita
    if isinstance(no.op, ast.Div):
        # Checar antes de dividir: ZeroDivisionError vira mensagem legível pro modelo
        if direita == 0:
            msg = "Divisão por zero."
            raise ValueError(msg)
        return esquerda / direita
    if isinstance(no.op, ast.FloorDiv):
        if direita == 0:
            msg = "Divisão por zero."
            raise ValueError(msg)
        return esquerda // direita
    if isinstance(no.op, ast.Mod):
        if direita == 0:
            msg = "Divisão por zero."
            raise ValueError(msg)
        return esquerda % direita
    # Pow com expoente gigante trava o processo: 2**999999999 come toda a RAM
    if isinstance(no.op, ast.Pow):
        if abs(direita) > 100:
            msg = "Expoente muito grande (máximo 100)."
            raise ValueError(msg)
        return esquerda**direita

    msg = f"Operador não suportado: {no.op.__class__.__name__}"
    raise ValueError(msg)


@tool
def calcular(expressao: str) -> str:
    """Calcula uma expressão aritmética e devolve o resultado exato.

    Use SEMPRE que a resposta envolver conta -- soma, multiplicação,
    porcentagem, total anual. Modelos de linguagem erram aritmética;
    esta ferramenta não erra.

    Args:
        expressao: expressão em notação Python. Ex: "890 * 12", "(300-50)/2".

    Returns:
        O resultado, ou uma mensagem explicando por que a expressão é inválida.
    """
    try:
        # mode="eval" aceita só UMA expressão -- não aceita comandos, atribuições, imports
        arvore = ast.parse(expressao, mode="eval")
        resultado = _avaliar_seguro(arvore)
    # Captura tanto nossos ValueError quanto erro de sintaxe da expressão
    except (ValueError, SyntaxError, TypeError) as erro:
        logger.warning("calcular(%r) falhou: %s", expressao, erro)
        # Devolver o erro COMO TEXTO deixa o modelo corrigir e tentar de novo
        return f"Não foi possível calcular: {erro}"

    # is_integer() checa se o float não tem casas decimais, pra imprimir 10680 e não 10680.0
    if resultado.is_integer():
        return str(int(resultado))
    # :g remove zeros à direita desnecessários na formatação
    return f"{resultado:g}"


# Lista única exportada: o agente importa daqui e não precisa saber os nomes um a um
FERRAMENTAS = [buscar_documentacao, calcular]
