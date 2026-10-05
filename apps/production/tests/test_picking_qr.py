"""QR kód na tištěné výdejce.

Papír se musí umět spárovat se svou výdejkou - jak pro otevření dokumentu
telefonem, tak pro budoucí dávkové rozpoznávání naskenovaných papírů.
"""
import base64
from datetime import date

from django.contrib.auth.models import User
from django.template.loader import render_to_string
from django.test import TestCase

from apps.canteens.models import Canteen
from apps.production.models import PickingListDocument
from apps.production.utils import picking_document_qr_uri


class PickingDocumentQrTest(TestCase):
    def setUp(self):
        self.canteen = Canteen.objects.create(name='Test Canteen')
        self.document = PickingListDocument.objects.create(
            name='Doc', canteen=self.canteen,
            date_from=date(2026, 10, 1), date_to=date(2026, 10, 1),
            created_by=User.objects.create_user(username='creator'),
        )

    def _svg(self, uri):
        prefix = 'data:image/svg+xml;base64,'
        self.assertTrue(uri.startswith(prefix))
        return base64.b64decode(uri[len(prefix):]).decode()

    def test_uri_is_svg_data_uri(self):
        svg = self._svg(picking_document_qr_uri(self.document, 'https://spiz.example/'))
        self.assertIn('<svg', svg)

    def test_different_documents_give_different_codes(self):
        other = PickingListDocument.objects.create(
            name='Doc2', canteen=self.canteen,
            date_from=date(2026, 10, 2), date_to=date(2026, 10, 2),
            created_by=self.document.created_by,
        )
        base = 'https://spiz.example/'
        self.assertNotEqual(
            picking_document_qr_uri(self.document, base),
            picking_document_qr_uri(other, base),
        )

    def test_relative_base_url_falls_back_to_plain_id(self):
        """Bez absolutní adresy (PDF z cronu) se do kódu nedá dát URL.

        Relativní cesta v QR by byla k ničemu, proto se kóduje jen označení
        dokumentu - papír jde pořád spárovat, jen se neotevře telefonem.
        """
        a = picking_document_qr_uri(self.document, '/')
        b = picking_document_qr_uri(self.document, 'https://spiz.example/')
        self.assertNotEqual(a, b)

    def test_template_embeds_qr_in_running_page_header(self):
        """QR je v běžící hlavičce, takže se tiskne na každé stránce dne."""
        uri = picking_document_qr_uri(self.document, 'https://spiz.example/')
        html = render_to_string('production/picking_list_pdf.html', {
            'canteen': self.canteen,
            'daily_picking_data': [(date(2026, 10, 1), [])],
            'qr_uri': uri,
        })
        self.assertIn('position: running(pageQr)', html)
        self.assertIn(uri, html)

    def test_template_without_qr_renders(self):
        """Starý volající bez qr_uri nesmí padnout ani vytisknout rozbitý obrázek."""
        html = render_to_string('production/picking_list_pdf.html', {
            'canteen': self.canteen,
            'daily_picking_data': [(date(2026, 10, 1), [])],
        })
        self.assertNotIn('<img class="qr"', html)
