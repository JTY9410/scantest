"""v2.2.29 UI completion tests."""

import pytest


class TestTemplateExists:
    """Test templates and routes exist."""
    
    def test_upload_template_has_checkbox(self, app):
        """Upload template contains force_full_scan checkbox."""
        with app.app_context():
            with open('app/templates/scanner/upload.html', 'r') as f:
                content = f.read()
        
        assert 'name="force_full_scan"' in content
        assert 'value="true"' in content
        assert '전체 스캔 강제' in content
        assert '수집 프로파일을 무시하고' in content
    
    def test_raw_viewer_template_has_collection_method(self, app):
        """Raw viewer template displays collection method."""
        with app.app_context():
            with open('app/templates/admin/raw_viewer.html', 'r') as f:
                content = f.read()
        
        assert '수집 방식' in content
        assert 'collection_method' in content
    
    def test_inspection_template_has_collection_method(self, app):
        """Inspection template displays collection method."""
        with app.app_context():
            with open('app/templates/scanner/inspection.html', 'r') as f:
                content = f.read()
        
        assert '수집 방식' in content
        assert 'view.collection_method' in content
