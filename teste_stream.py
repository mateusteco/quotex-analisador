"""Sondagem AUDUSD OTC, com o mesmo contrato do fluxo integrado."""
from teste_integrado_m1 import executar

if __name__ == '__main__':
    try:
        # A sondagem curta verifica ticks; o teste M1 completo exige aquecimento.
        executar(duracao=20, exigir_m1=False)
    except (RuntimeError, ValueError) as erro:
        print(str(erro))
        raise SystemExit(1) from None
