# Copyright 2020 Canonical Ltd.
# Licensed under the Apache License, Version 2.0; see LICENCE file for details.

import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from ops.testing import Harness
from ops.charm import CharmBase

import k8s
from k8s import (
    APIServer,
    PodStatus,
)


class GetPodStatusTest(unittest.TestCase):
    def get_harness(self, charm_name=None):
        class MyCharm(CharmBase):
            pass

        if charm_name is None:
            charm_name = uuid4()
        harness = Harness(MyCharm, meta="{{name: {!r}}}".format(charm_name))
        harness.set_model_name(uuid4())
        self.addCleanup(harness.cleanup)
        harness.begin()

        return harness

    def load_a_pod_status_response(self):
        with (Path(__file__).parent / "a_pod_status.json").open("rt", encoding="utf8") as f:
            return json.load(f)

    @patch("k8s.APIServer", autospec=True, spec_set=True)
    def test_fetch__returns_a_PodStatus_obj_if_resource_found(self, mock_api_server_cls):
        # Setup
        juju_unit = uuid4()

        mock_api_server = mock_api_server_cls.return_value
        mock_api_server.get.return_value = {
            "kind": "PodList",
            "items": [{"metadata": {"annotations": {"juju.io/unit": juju_unit}}}],
        }

        # Exercise
        pod_status = k8s.PodStatus.fetch(juju_model=uuid4(), juju_app=uuid4(), juju_unit=juju_unit)

        # Assert
        assert type(pod_status) == PodStatus

    @patch("k8s.APIServer", autospec=True, spec_set=True)
    def test_for_charm__returns_a_PodStatus_obj_if_resource_found(self, mock_api_server_cls):
        # Setup
        harness = self.get_harness()
        juju_unit = harness.charm.unit.name

        mock_api_server = mock_api_server_cls.return_value
        mock_api_server.get.return_value = {
            "kind": "PodList",
            "items": [{"metadata": {"annotations": {"juju.io/unit": juju_unit}}}],
        }

        # Exercise
        pod_status = k8s.PodStatus.for_charm(harness.charm)

        # Assert
        assert type(pod_status) == PodStatus

    @patch("k8s.APIServer", autospec=True, spec_set=True)
    def test_fetch__works(self, mock_api_server_cls):
        mock_api_server = mock_api_server_cls.return_value
        mock_api_server.get.return_value = self.load_a_pod_status_response()
        pod_status = k8s.PodStatus.fetch("my-model", "my-app", "charm-k8s-cassandra/0")

        assert not pod_status.is_unknown
        assert pod_status.is_running
        assert pod_status.is_ready

    @patch("k8s.APIServer", autospec=True, spec_set=True)
    def test_for_charm__works(self, mock_api_server_cls):
        # a_pod_status.json has data form 'charm-k8s-cassandra'
        harness = self.get_harness("charm-k8s-cassandra")
        mock_api_server = mock_api_server_cls.return_value
        mock_api_server.get.return_value = self.load_a_pod_status_response()

        pod_status = k8s.PodStatus.for_charm(harness.charm)

        assert not pod_status.is_unknown
        assert pod_status.is_running
        assert pod_status.is_ready

    @patch("k8s.APIServer", autospec=True, spec_set=True)
    def test__returns_PodStatus_even_if_resource_not_found(self, mock_api_server_cls):
        # Setup
        mock_api_server = mock_api_server_cls.return_value
        mock_api_server.get.return_value = {"kind": "PodList", "items": []}

        # Exercise
        pod_status = k8s.PodStatus.fetch(juju_model=uuid4(), juju_app=uuid4(), juju_unit=uuid4())

        # Assert
        assert type(pod_status) == PodStatus


class APIServerTest(unittest.TestCase):
    @patch("k8s.open", create=True)
    @patch("k8s.ssl.SSLContext", autospec=True, spec_set=True)
    @patch("k8s.http.client.HTTPSConnection", autospec=True, spec_set=True)
    def test__get__loads_json_string_successfully(
        self, mock_https_connection_cls, mock_ssl_context_cls, mock_open
    ):
        # Setup
        mock_token = str(uuid4())
        mock_token_file = io.StringIO(mock_token)
        mock_open.return_value = mock_token_file
        mock_response_dict = {}
        mock_response_json = io.StringIO(json.dumps(mock_response_dict))
        mock_response_json.status = 200

        mock_conn = mock_https_connection_cls.return_value
        mock_conn.getresponse.return_value = mock_response_json

        # Exercise
        api_server = APIServer()
        response = api_server.get("/some/path")

        # Assert
        assert response == mock_response_dict


class PodStatusTest(unittest.TestCase):
    def test__pod_is_not_running_yet(self):
        # Setup
        status_dict = {
            "metadata": {"annotations": {"juju.io/unit": uuid4()}},
            "status": {
                "phase": "Pending",
                "conditions": [{"type": "ContainersReady", "status": "False"}],
            },
        }

        # Exercise
        pod_status = PodStatus(**status_dict)

        # Assert
        assert not pod_status.is_unknown
        assert not pod_status.is_running
        assert not pod_status.is_ready

    def test__pod_is_ready(self):
        # Setup
        status_dict = {
            "metadata": {"annotations": {"juju.io/unit": uuid4()}},
            "status": {
                "phase": "Running",
                "conditions": [{"type": "ContainersReady", "status": "True"}],
            },
        }

        # Exercise
        pod_status = PodStatus(**status_dict)

        # Assert
        assert not pod_status.is_unknown
        assert pod_status.is_running
        assert pod_status.is_ready

    def test__pod_is_running_but_not_yet_ready_to_serve(self):
        # Setup
        status_dict = {
            "metadata": {"annotations": {"juju.io/unit": uuid4()}},
            "status": {
                "phase": "Running",
                "conditions": [{"type": "ContainersReady", "status": "False"}],
            },
        }

        # Exercise
        pod_status = PodStatus(**status_dict)

        # Assert
        assert not pod_status.is_unknown
        assert pod_status.is_running
        assert not pod_status.is_ready

    def test__status_is_unknown(self):
        # Exercise
        pod_status = PodStatus()

        # Assert
        assert pod_status.is_unknown
        assert not pod_status.is_running
        assert not pod_status.is_ready

    def test__pod_status_incomplete(self):
        # Setup
        status_dict = {"metadata": {}}

        # Exercise
        pod_status = PodStatus(**status_dict)

        # Assert
        assert not pod_status.is_unknown
        assert not pod_status.is_running
        assert not pod_status.is_ready
