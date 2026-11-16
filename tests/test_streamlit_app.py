"""Pruebas de renderizado real con el simulador de Streamlit."""
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "streamlit_app.py"


class AppSmokeTest(unittest.TestCase):
    def test_initial_page_renders(self):
        at = AppTest.from_file(str(APP_PATH)).run(timeout=30)
        self.assertEqual(len(at.exception), 0, [str(x) for x in at.exception])
        self.assertGreater(len(at.title), 0)

    def test_click_runs_synthetic_simulation_and_renders_dashboard(self):
        at = AppTest.from_file(str(APP_PATH)).run(timeout=30)
        self.assertEqual(len(at.exception), 0)
        self.assertGreaterEqual(len(at.form_submit_button), 1)
        at.form_submit_button[0].click().run(timeout=45)
        self.assertEqual(len(at.exception), 0, [str(x) for x in at.exception])
        nav=next(r for r in at.radio if r.label=="Navegación principal")
        nav.set_value("🗂️ Histórico y herramientas").run(timeout=45)
        self.assertEqual(len(at.exception), 0, [str(x) for x in at.exception])
        self.assertGreaterEqual(len(at.metric), 4)
        self.assertGreaterEqual(len(at.tabs), 1)

    def test_all_sections_are_navigable_without_data(self):
        at=AppTest.from_file(str(APP_PATH)).run(timeout=30)
        for section in ("📊 Rendimiento","🌍 Investigación","⚡ Simulación rápida",
                        "🔺 Nory multiactivo"):
            nav=next(r for r in at.radio if r.label=="Navegación principal")
            nav.set_value(section).run(timeout=45)
            self.assertFalse(at.exception,
                             f"Navigation {section}: {[str(x) for x in at.exception]}")


if __name__ == "__main__":
    unittest.main()
