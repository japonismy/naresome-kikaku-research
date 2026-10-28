import unittest
import test_baseline_registry as registry_helpers

class RequestedRestorationTests(unittest.TestCase):
    def test_owner_approved_channels_are_public_without_duplicate_ids(self):
        rows=[{'canonical_channel_id':'UCqQz6LVzjVFhwuptIARMOEw','channel_name':'俺たちの馴れ初め','portal_scope':''},
              {'canonical_channel_id':'UChcGiinrSBYGTNOfhU1A_SQ','channel_name':'スミレフィルム','portal_scope':''}]
        result=registry_helpers.RegistryTests().read(rows)
        self.assertEqual({r['canonical_channel_id'] for r in result},{r['canonical_channel_id'] for r in rows})

if __name__=='__main__':unittest.main()
