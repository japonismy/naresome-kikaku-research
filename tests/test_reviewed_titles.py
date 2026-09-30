import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import generate_portal_data_bq as portal

class ReviewedTitlesTest(unittest.TestCase):
    def test_override_is_limited_to_exact_reviewed_id_and_title(self):
        title='A reviewed nonadult title'
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)
            with (path/'reviewed_nonadult_titles.csv').open('w',encoding='utf-8',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=['video_id','reviewed_title']);writer.writeheader();writer.writerow({'video_id':'reviewed','reviewed_title':title})
            items=[{'video_id':'reviewed','title':title,'content_flags':['adult']},{'video_id':'other','title':title},{'video_id':'reviewed','title':'changed adult title'}]
            with patch.object(portal,'SOURCE_DIR',path),patch.object(portal,'ADULT_TITLE_RE') as regex:
                regex.search.return_value=True
                portal.classify_videos(items,{})
            self.assertEqual([i['default_visible'] for i in items],[True,False,False])
    def test_channel_exclusion_is_not_overridden(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)
            (path/'reviewed_nonadult_titles.csv').write_text('video_id,reviewed_title\nv,title\n',encoding='utf-8')
            item={'video_id':'v','title':'title','channel':'excluded'}
            with patch.object(portal,'SOURCE_DIR',path):
                portal.classify_videos([item],{'excluded':{'classification':'adult','reason':'channel exclusion'}})
            self.assertFalse(item['default_visible'])
