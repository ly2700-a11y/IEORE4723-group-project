import unittest
from streamlit.testing.v1 import AppTest
from mandate.workflow import ROOT

class InterfaceTests(unittest.TestCase):
    def test_sequential_flow_and_demo(self):
        app=AppTest.from_file(str(ROOT/'app.py')).run(timeout=30)
        self.assertFalse(list(app.exception))
        self.assertEqual([t.label for t in app.tabs],['① Documents and rules','② Holdings and trade checks','③ Explanation and remediation','④ Public resources'])
        self.assertEqual(len(app.metric),0)
        app.sidebar.radio[0].set_value('Teaching demo').run()
        self.assertFalse(list(app.exception))
        self.assertEqual([x.value for x in app.metric],['PASS','FAIL','PASS'])
        app.sidebar.radio[0].set_value('Real fund workflow').run()
        self.assertFalse(list(app.exception));self.assertEqual(len(app.metric),0)
    def test_public_document_package(self):
        app=AppTest.from_file(str(ROOT/'app.py')).run(timeout=30)
        app.checkbox[0].check().run(timeout=60)
        self.assertFalse(list(app.exception))
        self.assertEqual(len(app.metric),0)
        self.assertTrue(any('All document text' in c.value for c in app.caption))
