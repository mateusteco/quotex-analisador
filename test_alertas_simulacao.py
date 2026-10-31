"""Testes locais de alertas; nao usa OTCharts nem envia mensagens reais."""
import unittest
from unittest.mock import Mock, patch
from alertas_simulacao import formatar_alerta, enviar_alerta

class TestAlertas(unittest.TestCase):
    def setUp(self):
        self.leitura = {"inicio": 1760000000, "preco": 1.2345, "mm9": 1.233,
                        "mm21": 1.231, "rsi14": 62.4, "sinal_teorico": "CALL"}

    def test_sem_sinal_nao_envia(self):
        leitura = dict(self.leitura, sinal_teorico=None)
        self.assertIsNone(formatar_alerta(leitura))
        self.assertFalse(enviar_alerta(leitura))

    def test_texto_marca_simulacao(self):
        mensagem = formatar_alerta(self.leitura)
        self.assertIn("TESTE", mensagem)
        self.assertIn("SIMULAÇÃO", mensagem)
        self.assertIn("CALL", mensagem)

    @patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "teste", "TELEGRAM_CHAT_ID": "123"})
    def test_envio_simulado_sem_rede(self):
        resposta = Mock()
        resposta.json.return_value = {"ok": True}
        cliente = Mock()
        cliente.post.return_value = resposta
        self.assertTrue(enviar_alerta(self.leitura, sessao=cliente))
        cliente.post.assert_called_once()
        self.assertIn("sendMessage", cliente.post.call_args.args[0])

if __name__ == "__main__":
    unittest.main()
