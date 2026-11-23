"""Pruebas locales: sin red, cuentas ni variables SMTP reales."""
import os
import unittest
from email.utils import parseaddr
from unittest.mock import patch

import alertas


class PruebasCorreo(unittest.TestCase):
    def test_confirmacion_y_escape(self):
        salida = alertas._html_confirmacion('<codigo&"peligroso">', 'semanal<script>')
        self.assertIn('&lt;codigo&amp;&quot;peligroso&quot;&gt;', salida)
        self.assertIn('semanal&lt;script&gt;', salida)
        self.assertNotIn('<script>', salida)
        self.assertIn('El código vence en 24 horas', salida)
        self.assertIn('Radar de contrataciones públicas', salida)

    def test_resumen_y_cancelacion(self):
        filas = [{'titulo': '<img src=x onerror=alert(1)>', 'ocid': 'a&b', 'cierre': '"mañana"'}]
        salida = alertas._html_resumen(filas, '<token&>', 'mensual')
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', salida)
        self.assertNotIn('<img src=x', salida)
        self.assertIn('a&amp;b', salida)
        self.assertIn('&quot;mañana&quot;', salida)
        self.assertIn('&lt;token&amp;&gt;', salida)
        self.assertIn('Cancelar alerta de LicitIA', salida)

    def test_resumen_vacio(self):
        self.assertIn('Sin coincidencias', alertas._html_resumen([], 'demo', 'semanal'))

    def test_multipart_y_starttls(self):
        class SMTPFalso:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.tls = False
                self.mensaje = None

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def starttls(self, *, context):
                self.tls = True

            def login(self, user, password):
                raise AssertionError('No debería autenticarse en esta prueba')

            def send_message(self, mensaje):
                self.mensaje = mensaje
                self.partes = [parte.get_content_type() for parte in mensaje.iter_parts()]
                self.from_header = mensaje['From']
                self.texto = mensaje.get_body(preferencelist=('plain',)).get_content()

        instancias = []
        def construir(*args, **kwargs):
            smtp = SMTPFalso(*args, **kwargs)
            instancias.append(smtp)
            return smtp

        with patch.dict(os.environ, {'SMTP_HOST': 'smtp.gmail.com', 'SMTP_PORT': '587',
                                     'SMTP_FROM': 'remitente@ejemplo.test', 'SMTP_USER': ''}):
            with patch.object(alertas.smtplib, 'SMTP', side_effect=construir):
                alertas.enviar('destinatario@ejemplo.test', 'Prueba', 'Respaldo plano',
                              contenido_html=alertas._html_confirmacion('EJEMPLO', 'semanal'))

        smtp = instancias[0]
        self.assertEqual(smtp.args[:2], ('smtp.gmail.com', 587))
        self.assertTrue(smtp.tls)
        self.assertEqual(smtp.partes, ['text/plain', 'text/html'])
        self.assertEqual(parseaddr(smtp.from_header), ('LicitIA', 'remitente@ejemplo.test'))
        self.assertEqual(smtp.texto.strip(), 'Respaldo plano')


if __name__ == '__main__':
    unittest.main()
