import connexion
import six

from tsfdb_server_v1.models.error import Error  # noqa: E501
from tsfdb_server_v1.models.resource import Resource  # noqa: E501
from tsfdb_server_v1 import util
from .helpers import find_metrics


def list_metrics_by_resource(resource_id, x_org_id):  # noqa: E501
    """Return metrics and metadata for a specific resource

     # noqa: E501

    :param resource_id: The id of the resource to retrieve
    :type resource_id: str
    :param x_org_id: Organization id
    :type x_org_id: str

    :rtype: Resource
    """
    data = find_metrics(resource_id)
    if isinstance(data, Error):
        return data
    else:
        return Resource(id=resource_id, metrics=data)


def list_resources(limit=None):  # noqa: E501
    """List all monitored resources

     # noqa: E501

    :param limit: How many items to return at one time (max 100)
    :type limit: int

    :rtype: List[Resource]
    """
    return 'do some magic!'
