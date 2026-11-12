import unittest,tempfile,contextlib,io,sys
from pathlib import Path
from unittest.mock import patch
import render_slides as renderer

class OfficePriority(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.r=Path(self.tmp.name)
 def test_installed_powerpoint_selects_native_route(self):
  with patch.object(renderer,'ms_powerpoint_installed',return_value=True),patch.object(renderer,'_render_powerpoint',return_value=['native']) as native,patch.object(renderer,'_run_converter') as alternate:
   self.assertEqual(renderer.render(self.r/'a.pptx',self.r/'out'),['native']);native.assert_called_once();alternate.assert_not_called()
 def test_native_failure_never_falls_back_to_libreoffice(self):
  with patch.object(renderer,'ms_powerpoint_installed',return_value=True),patch.object(renderer,'_render_powerpoint',side_effect=renderer.NativeOfficeRenderError('actual native failure')),patch.object(renderer,'_run_converter') as alternate:
   with self.assertRaises(renderer.NativeOfficeRenderError):renderer.render(self.r/'a.pptx',self.r/'out')
   alternate.assert_not_called()
 def test_uncertain_installation_does_not_silently_choose_alternative(self):
  with patch.object(renderer,'ms_powerpoint_installed',side_effect=PermissionError('registry unavailable')),patch.object(renderer,'_run_converter') as alternate:
   with self.assertRaises(PermissionError):renderer.render(self.r/'a.pptx',self.r/'out')
   alternate.assert_not_called()
 def test_preflight_nonzero_propagates_from_cli(self):
  with patch.object(sys,'argv',['render','a.pptx',str(self.r/'out')]),patch.object(renderer,'render',side_effect=renderer.NativeOfficeRenderError('failed_preflight',2)),contextlib.redirect_stderr(io.StringIO()):
   self.assertEqual(renderer.main(),2)
 def test_native_execution_failure_propagates_from_cli(self):
  with patch.object(sys,'argv',['render','a.pptx',str(self.r/'out')]),patch.object(renderer,'render',side_effect=renderer.NativeOfficeRenderError('timeout',3)),contextlib.redirect_stderr(io.StringIO()):
   self.assertEqual(renderer.main(),3)
 def test_native_other_platform_keeps_ms_office_requirement(self):
  with patch.object(renderer.sys,'platform','darwin'),patch.object(renderer,'_run_converter') as alternate:
   with self.assertRaisesRegex(renderer.NativeOfficeRenderError,'native export'):renderer._render_powerpoint(self.r/'a.pptx',self.r/'out',144,30)
   alternate.assert_not_called()
 def test_wsl_detects_host_office(self):
  with patch.object(renderer.sys,'platform','linux'),patch.dict(renderer.os.environ,{'WSL_DISTRO_NAME':'Ubuntu'}),patch.object(renderer.Path,'is_file',return_value=True):
   self.assertTrue(renderer.ms_powerpoint_installed())
 def test_wsl_unknown_host_does_not_assume_no_office(self):
  with patch.object(renderer.sys,'platform','linux'),patch.dict(renderer.os.environ,{'WSL_DISTRO_NAME':'Ubuntu'}),patch.object(renderer.Path,'is_file',return_value=False),patch.object(renderer,'_probe_windows_host',side_effect=renderer.NativeOfficeRenderError('Windows host unknown')),patch.object(renderer,'_run_converter') as alternate:
   with self.assertRaisesRegex(renderer.NativeOfficeRenderError,'Windows host'):renderer.render(self.r/'a.pptx',self.r/'out')
   alternate.assert_not_called()
 def test_host_probe_distinguishes_installed_absent_and_error(self):
  from types import SimpleNamespace
  with patch.object(renderer.shutil,'which',return_value='powershell.exe'):
   for code,expected in [(0,True),(10,False)]:
    with patch.object(renderer.subprocess,'run',return_value=SimpleNamespace(returncode=code)) as run:
     self.assertEqual(renderer._probe_windows_host(),expected);self.assertEqual(run.call_args.kwargs['timeout'],10)
   with patch.object(renderer.subprocess,'run',return_value=SimpleNamespace(returncode=11)):
    with self.assertRaises(renderer.NativeOfficeRenderError):renderer._probe_windows_host()

if __name__=='__main__':unittest.main()
