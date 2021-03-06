# Copyright (c) 2010-2011 OpenStack, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import unittest
import os
import time
import uuid
import sqlite3
from shutil import rmtree
from slogging import db_stats_collector
from tempfile import mkdtemp
from test_slogging.unit import FakeLogger
from swift.account.backend import AccountBroker
from swift.container.backend import ContainerBroker
from swift.common.utils import mkdirs


class TestDbStats(unittest.TestCase):

    def setUp(self):
        self._was_logger = db_stats_collector.get_logger
        db_stats_collector.get_logger = FakeLogger
        self.testdir = os.path.join(mkdtemp(), 'tmp_test_db_stats')
        self.devices = os.path.join(self.testdir, 'node')
        rmtree(self.testdir, ignore_errors=1)
        mkdirs(os.path.join(self.devices, 'sda'))
        self.accounts = os.path.join(self.devices, 'sda', 'accounts')
        self.containers = os.path.join(self.devices, 'sda', 'containers')
        self.log_dir = '%s/log' % self.testdir

        self.conf = dict(devices=self.devices,
                         log_dir=self.log_dir,
                         mount_check='false')

    def tearDown(self):
        db_stats_collector.get_logger = self._was_logger
        rmtree(self.testdir)

    def test_account_stat_get_data(self):
        stat = db_stats_collector.AccountStatsCollector(self.conf)
        account_db = AccountBroker("%s/acc.db" % self.accounts,
                                        account='test_acc')
        account_db.initialize()
        account_db.put_container('test_container', time.time(),
                                      None, 10, 1000)
        info = stat.get_data("%s/acc.db" % self.accounts)
        self.assertEquals('''"test_acc",1,10,1000\n''', info)

    def test_container_stat_get_data(self):
        stat = db_stats_collector.ContainerStatsCollector(self.conf)
        container_db = ContainerBroker("%s/con.db" % self.containers,
                                     account='test_acc', container='test_con')
        container_db.initialize()
        container_db.put_object('test_obj', time.time(), 10, 'text', 'faketag')
        info = stat.get_data("%s/con.db" % self.containers)
        self.assertEquals('''"test_acc","test_con",1,10\n''', info)

    def test_container_stat_get_metadata(self):
        stat = db_stats_collector.ContainerStatsCollector(self.conf)
        container_db = ContainerBroker("%s/con.db" % self.containers,
                                     account='test_acc', container='test_con')
        container_db.initialize()
        container_db.put_object('test_obj', time.time(), 10, 'text', 'faketag')
        info = stat.get_data("%s/con.db" % self.containers)
        self.assertEquals('''"test_acc","test_con",1,10\n''', info)
        container_db.update_metadata({'test1': ('val', 1000)})

    def _gen_account_stat(self):
        stat = db_stats_collector.AccountStatsCollector(self.conf)
        output_data = set()
        for i in range(10):
            account_db = AccountBroker("%s/stats-201001010%s-%s.db" %
                                       (self.accounts, i, uuid.uuid4().hex),
                                        account='test_acc_%s' % i)
            account_db.initialize()
            account_db.put_container('test_container', time.time(),
                                      None, 10, 1000)
            # this will "commit" the data
            account_db.get_info()
            output_data.add('''"test_acc_%s",1,10,1000''' % i),

        self.assertEqual(len(output_data), 10)
        return stat, output_data

    def _drop_metadata_col(self, broker, acc_name):
        broker.conn.execute('''drop table container_stat''')
        broker.conn.executescript("""
            CREATE TABLE container_stat (
                account TEXT DEFAULT '%s',
                container TEXT DEFAULT 'test_con',
                created_at TEXT,
                put_timestamp TEXT DEFAULT '0',
                delete_timestamp TEXT DEFAULT '0',
                object_count INTEGER,
                bytes_used INTEGER,
                reported_put_timestamp TEXT DEFAULT '0',
                reported_delete_timestamp TEXT DEFAULT '0',
                reported_object_count INTEGER DEFAULT 0,
                reported_bytes_used INTEGER DEFAULT 0,
                hash TEXT default '00000000000000000000000000000000',
                id TEXT,
                status TEXT DEFAULT '',
                status_changed_at TEXT DEFAULT '0'
            );

            INSERT INTO container_stat (object_count, bytes_used)
                VALUES (1, 10);
        """ % acc_name)

    def _gen_container_stat(self, set_metadata=False, drop_metadata=False):
        if set_metadata:
            self.conf['metadata_keys'] = 'test1,test2'
            # webob runs title on all headers
        stat = db_stats_collector.ContainerStatsCollector(self.conf)
        output_data = set()
        for i in range(10):
            cont_db = ContainerBroker(
                "%s/container-stats-201001010%s-%s.db" % (self.containers, i,
                                                          uuid.uuid4().hex),
                 account='test_acc_%s' % i, container='test_con')
            cont_db.initialize()
            cont_db.put_object('test_obj', time.time(), 10, 'text', 'faketag')
            metadata_output = ''
            if set_metadata:
                if i % 2:
                    cont_db.update_metadata({'X-Container-Meta-Test1': (5, 1)})
                    metadata_output = ',1,'
                else:
                    cont_db.update_metadata({'X-Container-Meta-Test2': (7, 2)})
                    metadata_output = ',,1'
            # this will "commit" the data
            cont_db.get_info()
            if drop_metadata:
                output_data.add('''"test_acc_%s","test_con",1,10,,''' % i)
            else:
                output_data.add('''"test_acc_%s","test_con",1,10%s''' %
                                (i, metadata_output))
            if drop_metadata:
                self._drop_metadata_col(cont_db, 'test_acc_%s' % i)

        self.assertEqual(len(output_data), 10)
        return stat, output_data

    def test_account_stat_run_once_account(self):
        stat, output_data = self._gen_account_stat()
        stat.run_once()
        stat_file = os.listdir(self.log_dir)[0]
        with open(os.path.join(self.log_dir, stat_file)) as stat_handle:
            for i in range(10):
                data = stat_handle.readline()
                output_data.discard(data.strip())

        self.assertEqual(len(output_data), 0)

    def test_account_stat_run_once_bad_db(self):
        stat, output_data = self._gen_account_stat()

        def raise_error(path):
            raise sqlite3.OperationalError('Test error')
        stat.get_data = raise_error
        was_errors = len(stat.logger.log_dict['info'])
        stat.run_once()

    def test_account_stat_run_once_container_metadata(self):

        stat, output_data = self._gen_container_stat(set_metadata=True)
        stat.run_once()
        stat_file = os.listdir(self.log_dir)[0]
        with open(os.path.join(self.log_dir, stat_file)) as stat_handle:
            headers = stat_handle.readline()
            self.assert_(headers.startswith('Account Hash,Container Name,'))
            for i in range(10):
                data = stat_handle.readline()
                output_data.discard(data.strip())

        self.assertEqual(len(output_data), 0)

    def test_account_stat_run_once_container_no_metadata(self):

        stat, output_data = self._gen_container_stat(set_metadata=True,
                                                     drop_metadata=True)
        stat.run_once()
        stat_file = os.listdir(self.log_dir)[0]
        with open(os.path.join(self.log_dir, stat_file)) as stat_handle:
            headers = stat_handle.readline()
            self.assert_(headers.startswith('Account Hash,Container Name,'))
            for i in range(10):
                data = stat_handle.readline()
                output_data.discard(data.strip())

        self.assertEqual(len(output_data), 0)

    def test_account_stat_run_once_both(self):
        acc_stat, acc_output_data = self._gen_account_stat()
        con_stat, con_output_data = self._gen_container_stat()

        acc_stat.run_once()
        stat_file = os.listdir(self.log_dir)[0]
        with open(os.path.join(self.log_dir, stat_file)) as stat_handle:
            for i in range(10):
                data = stat_handle.readline()
                acc_output_data.discard(data.strip())

        self.assertEqual(len(acc_output_data), 0)

        con_stat.run_once()
        stat_file = [f for f in os.listdir(self.log_dir) if f != stat_file][0]
        with open(os.path.join(self.log_dir, stat_file)) as stat_handle:
            headers = stat_handle.readline()
            self.assert_(headers.startswith('Account Hash,Container Name,'))
            for i in range(10):
                data = stat_handle.readline()
                con_output_data.discard(data.strip())

        self.assertEqual(len(con_output_data), 0)

    def test_account_stat_run_once_fail(self):
        stat, output_data = self._gen_account_stat()
        rmtree(self.accounts)
        stat.run_once()
        self.assertEquals(len(stat.logger.log_dict['debug']), 1)

    def test_not_implemented(self):
        db_stat = db_stats_collector.DatabaseStatsCollector(self.conf,
                                     'account', 'test_dir', 'stats-%Y%m%d%H_')
        self.assertRaises(NotImplementedError, db_stat.get_data)
        self.assertRaises(NotImplementedError, db_stat.get_header)

    def test_not_not_mounted(self):
        self.conf['mount_check'] = 'true'
        stat, output_data = self._gen_account_stat()
        stat.run_once()
        self.assertEquals(len(stat.logger.log_dict['error']), 1)

if __name__ == '__main__':
    unittest.main()
