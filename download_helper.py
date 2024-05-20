from data_definitions import (
    ErrorResponse,
    GeodesignhubProjectBounds,
    GeodesignhubSystem,
    GeodesignhubProjectData,
    GeodesignhubFeatureProperties,
    BuildingData,
    GeodesignhubDataShadowGenerationRequest,
    GeodesignhubDesignFeatureProperties,
    RoadsDownloadRequest,
    TreesDownloadRequest,
    GeodesignhubProjectCenter,
    RoadsShadowsComputationStartRequest,
    BuildingsDownloadRequest,
    ExistingBuildingsDataShadowGenerationRequest,
    GeodesignhubProjectTags,
    GeodesignhubSystemDetail,
    TreeFeatureProperties,
    DiagramUploadDetails,
    UploadSuccessResponse,
)
import utils
from shapely.geometry.base import BaseGeometry
from shapely.geometry import mapping, shape
import json
from dataclasses import asdict
from dacite import from_dict
from typing import List, Optional, Union
from geojson import Feature, FeatureCollection, Polygon, LineString, Point
import GeodesignHub, config
from conn import get_redis
from dotenv import load_dotenv, find_dotenv
from dataclasses import asdict
from notifications_helper import (
    notify_shadow_complete,
    shadow_generation_failure,
    notify_roads_download_complete,
    notify_roads_download_failure,
    notify_gdh_roads_shadow_intersection_complete,
    notify_gdh_roads_shadow_intersection_failure,
    notify_trees_download_complete,
    notify_trees_download_failure,
    notify_buildings_download_complete,
    notify_buildings_download_failure,
)
from uuid import uuid4
import uuid
from json import encoder
from rq import Queue
from rq.job import Dependency
from worker import conn
from config import wms_url_generator

load_dotenv(find_dotenv())

ENV_FILE = find_dotenv()
if ENV_FILE:
    load_dotenv(ENV_FILE)

redis = get_redis()
q = Queue(connection=conn)


class ShapelyEncoder(json.JSONEncoder):
    """Encodes JSON strings into shapes processed by SHapely"""

    def default(self, obj):
        if isinstance(obj, BaseGeometry):
            return mapping(obj)
        return json.JSONEncoder.default(self, obj)


def export_to_json(data):
    """Export a shapely output to JSON"""
    encoder.FLOAT_REPR = lambda o: format(o, ".6f")
    return json.loads(json.dumps(data, sort_keys=True, cls=ShapelyEncoder))


class GeodesignhubDataDownloader:
    """
    A class to download data from Geodesignhub
    """

    def __init__(
        self,
        session_id: uuid4,
        project_id: str,
        apitoken: str,
        cteam_id=None,
        synthesis_id=None,
        diagram_id=None,
    ):
        self.session_id = session_id
        self.project_id = project_id
        self.apitoken = apitoken
        self.cteam_id = cteam_id
        self.synthesis_id = synthesis_id
        d = int(diagram_id) if diagram_id else None
        self.diagram_id = d
        self.api_helper = GeodesignHub.GeodesignHubClient(
            url=config.apisettings["serviceurl"],
            project_id=self.project_id,
            token=self.apitoken,
        )

    def download_project_systems(
        self,
    ) -> Union[ErrorResponse, List[GeodesignhubSystem]]:
        s = self.api_helper.get_all_systems()
        # Check responses / data
        try:
            assert s.status_code == 200
        except AssertionError as ae:
            error_msg = ErrorResponse(
                status=0,
                message="Could not parse Project ID, Diagram ID or API Token ID. One or more of these were not found in your JSON request.",
                code=400,
            )

            return error_msg

        systems = s.json()
        all_systems: List[GeodesignhubSystem] = []
        for s in systems:
            current_system = from_dict(data_class=GeodesignhubSystem, data=s)
            all_systems.append(current_system)

        return all_systems

    def download_project_bounds(
        self,
    ) -> Union[ErrorResponse, GeodesignhubProjectBounds]:
        b = self.api_helper.get_project_bounds()
        try:
            assert b.status_code == 200
        except AssertionError:
            error_msg = ErrorResponse(
                status=0,
                message="Could not parse Project ID, Diagram ID or API Token ID. One or more of these were not found in your JSON request.",
                code=400,
            )
            return error_msg

        bounds = from_dict(data_class=GeodesignhubProjectBounds, data=b.json())

        return bounds

    def download_project_tags(self) -> Union[ErrorResponse, GeodesignhubProjectTags]:
        t = self.api_helper.get_project_tags()
        try:
            assert t.status_code == 200
        except AssertionError:
            error_msg = ErrorResponse(
                status=0,
                message="Could not parse Project ID, Diagram ID or API Token ID. One or more of these were not found in your JSON request.",
                code=400,
            )
            return error_msg
        return t.json()

    def upload_diagram(
        self, diagram_upload_details: DiagramUploadDetails
    ) -> Union[ErrorResponse, UploadSuccessResponse]:

        upload_job = self.api_helper.post_as_diagram(
            geoms=json.loads(diagram_upload_details.geometry),
            projectorpolicy=diagram_upload_details.project_or_policy,
            featuretype=diagram_upload_details.feature_type,
            description=diagram_upload_details.description,
            sysid=diagram_upload_details.sys_id,
            fundingtype=diagram_upload_details.funding_type,
        )

        job_result = upload_job.json()

        if upload_job.status_code == 201:
            upload_result = UploadSuccessResponse(
                message="Successfully uploaded diagram", code=201, status=1
            )

        else:
            upload_result = ErrorResponse(
                message=job_result["status"], code=400, status=0
            )

        return upload_result

    def download_project_center(
        self,
    ) -> Union[ErrorResponse, GeodesignhubProjectCenter]:
        c = self.api_helper.get_project_center()
        try:
            assert c.status_code == 200
        except AssertionError:
            error_msg = ErrorResponse(
                status=0,
                message="Could not parse Project ID, Diagram ID or API Token ID. One or more of these were not found in your JSON request.",
                code=400,
            )

            return error_msg
        center = from_dict(data_class=GeodesignhubProjectCenter, data=c.json())
        return center

    def download_design_data_from_geodesignhub(
        self,
    ) -> Union[ErrorResponse, FeatureCollection]:
        r = self.api_helper.get_single_synthesis(
            teamid=int(self.cteam_id), synthesisid=self.synthesis_id
        )

        try:
            assert r.status_code == 200
        except AssertionError:
            error_msg = ErrorResponse(
                status=0,
                message="Could not parse Project ID, Diagram ID or API Token ID. One or more of these were not found in your JSON request.",
                code=400,
            )
            return error_msg

        _design_details_raw = r.json()

        return _design_details_raw

    def process_design_data_from_geodesignhub(
        self, unprocessed_design_geojson
    ) -> Union[ErrorResponse, FeatureCollection]:

        _all_features: List[Feature] = []
        # Populate Default building data if not available
        for _single_diagram_feature in unprocessed_design_geojson["features"]:
            _diagram_properties = _single_diagram_feature["properties"]
            _project_or_policy = _diagram_properties["areatype"]
            _diagram_properties["height"] = _diagram_properties["volume_information"][
                "max_height"
            ]
            _diagram_properties["base_height"] = _diagram_properties[
                "volume_information"
            ]["min_height"]
            _diagram_properties["diagram_id"] = _diagram_properties["diagramid"]
            _diagram_properties["building_id"] = str(uuid.uuid4())
            _feature_properties = from_dict(
                data_class=GeodesignhubDesignFeatureProperties, data=_diagram_properties
            )

            if _project_or_policy == "policy":
                point_grid = utils.create_point_grid(
                    geojson_feature=_single_diagram_feature
                )

                _feature_properties.height = 0
                _feature_properties.base_height = 0
                for _point_feature in point_grid["features"]:
                    _point_geometry = Polygon(
                        coordinates=_point_feature["geometry"]["coordinates"]
                    )
                    _feature = Feature(
                        geometry=_point_geometry, properties=asdict(_feature_properties)
                    )
                    _all_features.append(_feature)
            else:
                # We assume that GDH will provide a polygon
                if _single_diagram_feature["geometry"]["type"] == "Polygon":
                    _geometry = Polygon(
                        coordinates=_single_diagram_feature["geometry"]["coordinates"]
                    )
                elif _single_diagram_feature["geometry"]["type"] == "LineString":
                    _geometry = LineString(
                        coordinates=_single_diagram_feature["geometry"]["coordinates"]
                    )
                elif _single_diagram_feature["geometry"]["type"] == "Point":
                    point = shape(_single_diagram_feature["geometry"])
                    buffered_point = point.buffer(0.00005)
                    buffered_polygon = export_to_json(buffered_point)
                    _geometry = Polygon(coordinates=buffered_polygon["coordinates"])
                    # Buffer the point

                else:
                    error_msg = ErrorResponse(
                        status=0,
                        message="Building shadows can only be computed for polygon features, you are trying to compute shadows for .",
                        code=400,
                    )
                    return None
                _feature = Feature(
                    geometry=_geometry, properties=asdict(_feature_properties)
                )
                _all_features.append(_feature)

        _diagram_feature_collection = FeatureCollection(features=_all_features)

        return _diagram_feature_collection

    def download_diagram_data_from_geodesignhub(
        self,
    ) -> Union[ErrorResponse, FeatureCollection]:
        my_api_helper = GeodesignHub.GeodesignHubClient(
            url=config.apisettings["serviceurl"],
            project_id=self.project_id,
            token=self.apitoken,
        )
        # Download Data
        d = my_api_helper.get_single_diagram(diagid=self.diagram_id)

        try:
            assert d.status_code == 200
        except AssertionError:
            error_msg = ErrorResponse(
                status=0,
                message="Could not parse Project ID, Diagram ID or API Token ID. One or more of these were not found in your JSON request.",
                code=400,
            )
            return error_msg

        _diagram_details_raw = d.json()
        # Populate Default building data if not available
        if not bool(_diagram_details_raw["building_data"]):
            _default_building_data = {
                "meters_above_ground": 10,
                "meters_below_ground": 0,
            }
        else:
            _default_building_data = _diagram_details_raw["building_data"]

        _diagram_details_feature_collection = _diagram_details_raw["geojson"]

        _all_features: List[Feature] = []
        for f in _diagram_details_feature_collection["features"]:
            _f_props = f["properties"]
            _building_data = BuildingData(
                height=_default_building_data["meters_above_ground"],
                base_height=_default_building_data["meters_below_ground"],
            )

            _diagram_details_raw["height"] = asdict(_building_data)["height"]
            _diagram_details_raw["base_height"] = asdict(_building_data)["base_height"]
            _diagram_details_raw["diagram_id"] = self.diagram_id
            _diagram_details_raw["building_id"] = str(uuid.uuid4())
            _diagram_details_raw["color"] = _f_props["color"]
            _feature_properties = from_dict(
                data_class=GeodesignhubFeatureProperties, data=_diagram_details_raw
            )

            # We assume that GDH will provide a polygon
            if f["geometry"]["type"] == "Polygon":
                _geometry = Polygon(coordinates=f["geometry"]["coordinates"])
            elif f["geometry"]["type"] == "LineString":
                _geometry = LineString(coordinates=f["geometry"]["coordinates"])
            else:
                error_msg = ErrorResponse(
                    status=0,
                    message="Building shadows can only be computed for polygon features, you are trying to compute shadows for .",
                    code=400,
                )
                return None
            _feature = Feature(
                geometry=_geometry, properties=asdict(_feature_properties)
            )
            _all_features.append(_feature)

        _diagram_feature_collection = FeatureCollection(features=_all_features)

        return _diagram_feature_collection

    def generate_tree_point_feature_collection(
        self, point_feature_list
    ) -> FeatureCollection:

        _all_tree_features: List[Feature] = []
        for point_feature in point_feature_list:
            _geometry = Point(coordinates=point_feature["geometry"]["coordinates"])
            _feature = Feature(geometry=_geometry, properties={})
            _all_tree_features.append(_feature)

        _trees_feature_collection = FeatureCollection(features=_all_tree_features)

        return _trees_feature_collection

    def filter_design_tree_points(
        self, unprocessed_design_geojson: FeatureCollection
    ) -> FeatureCollection:
        # This method filters the tree points out of a design Geojson

        _all_tree_features: List[Feature] = []
        # Populate Default building data if not available
        for f in unprocessed_design_geojson["features"]:
            if f["geometry"]["type"] in ["Point"]:
                _geometry = Point(coordinates=f["geometry"]["coordinates"])
                _diagram_properties = f["properties"]
                _tree_feature_properties = TreeFeatureProperties(
                    author=_diagram_properties["author"],
                    description=_diagram_properties["description"],
                )
                # _feature_properties = from_dict(
                #     data_class=GeodesignhubDesignFeatureProperties, data=_diagram_properties
                # )
                _feature = Feature(
                    geometry=_geometry, properties=asdict(_tree_feature_properties)
                )
                _all_tree_features.append(_feature)

        _trees_feature_collection = FeatureCollection(features=_all_tree_features)

        return _trees_feature_collection

    def filter_to_get_gi_system(
        self, geodesignhub_project_data: GeodesignhubProjectData
    ) -> int:
        geodesignhub_project_data = asdict(geodesignhub_project_data)
        interesting_system = [
            d for d in geodesignhub_project_data["systems"] if d["sysname"] == "TREE"
        ]
        return interesting_system[0]["id"]

    def download_project_data_from_geodesignhub(
        self,
    ) -> Union[ErrorResponse, GeodesignhubProjectData]:
        my_api_helper = GeodesignHub.GeodesignHubClient(
            url=config.apisettings["serviceurl"],
            project_id=self.project_id,
            token=self.apitoken,
        )
        # Download Data
        s = my_api_helper.get_all_systems()
        b = my_api_helper.get_project_bounds()
        c = my_api_helper.get_project_center()
        t = my_api_helper.get_project_tags()

        # Check responses / data
        try:
            assert s.status_code == 200
        except AssertionError:
            error_msg = ErrorResponse(
                status=0,
                message="Could not parse Project ID, Diagram ID or API Token ID. One or more of these were not found in your JSON request.",
                code=400,
            )
            return error_msg

        systems = s.json()
        all_systems: List[GeodesignhubSystem] = []
        all_system_details: List[GeodesignhubSystemDetail] = []
        for s in systems:
            current_system = from_dict(data_class=GeodesignhubSystem, data=s)
            sd = my_api_helper.get_single_system(system_id=current_system.id)
            sd_raw = sd.json()
            current_system_details = from_dict(
                data_class=GeodesignhubSystemDetail, data=sd_raw
            )
            all_system_details.append(current_system_details)
            all_systems.append(current_system)

        try:
            assert b.status_code == 200
        except AssertionError:
            error_msg = ErrorResponse(
                status=0,
                message="Could not parse Project ID, Diagram ID or API Token ID. One or more of these were not found in your JSON request.",
                code=400,
            )
            return error_msg

        center = from_dict(data_class=GeodesignhubProjectCenter, data=c.json())
        bounds = from_dict(data_class=GeodesignhubProjectBounds, data=b.json())
        tags = from_dict(data_class=GeodesignhubProjectTags, data={"tags": t.json()})
        project_data = GeodesignhubProjectData(
            systems=all_systems,
            system_details=all_system_details,
            bounds=bounds,
            center=center,
            tags=tags,
        )

        return project_data


class RoadsDownloadFactory:
    def __init__(
        self, session_id: str, bounds: str, project_id: str, shadow_date_time: str
    ):

        self.session_id = session_id
        self.shadow_date_time = shadow_date_time
        self.bounds = bounds
        self.project_id = project_id

    def start_download_roads_job(self):

        my_url_generator = wms_url_generator(project_id=self.project_id)
        r_url = my_url_generator.get_roads_url()

        roads_download_job = RoadsDownloadRequest(
            bounds=self.bounds,
            session_id=str(self.session_id),
            request_date_time=self.shadow_date_time,
            roads_url=r_url,
        )
        roads_download_result = q.enqueue(
            utils.download_roads,
            asdict(roads_download_job),
            on_success=notify_roads_download_complete,
            on_failure=notify_roads_download_failure,
            job_id=self.session_id + ":" + self.shadow_date_time + ":roads",
        )


class ShadowComputationHelper:
    def __init__(
        self,
        session_id: str,
        shadow_date_time: str,
        bounds: str,
        project_id: str,
        design_diagram_geojson=None,
    ):
        self.gdh_geojson = design_diagram_geojson
        self.session_id = session_id
        self.shadow_date_time = shadow_date_time
        self.bounds = bounds
        self.project_id = project_id

    def compute_gdh_buildings_shadow(self):
        """This method computes the shadow for existing or GDH buidlings"""
        my_url_generator = wms_url_generator(project_id=self.project_id)
        r_url = my_url_generator.get_roads_url()

        try:
            assert r_url != '0'

        except AssertionError:
            print("A Roads GeoJSON as a URL is expected")
        else:
            # first download the trees and then compute design shadow

            roads_download_job = RoadsDownloadRequest(
                bounds=self.bounds,
                session_id=str(self.session_id),
                request_date_time=self.shadow_date_time,
                roads_url=r_url,
            )
            roads_download_result = q.enqueue(
                utils.download_roads,
                asdict(roads_download_job),
                on_success=notify_roads_download_complete,
                on_failure=notify_roads_download_failure,
                job_id=self.session_id + ":" + self.shadow_date_time + ":roads",
            )

            gdh_buildings_shadow_dependency = Dependency(
                jobs=[roads_download_result], allow_failure=False, enqueue_at_front=True
            )

            # generate the GDH Shadows
            gdh_worker_data = GeodesignhubDataShadowGenerationRequest(
                buildings=self.gdh_geojson,
                session_id=self.session_id,
                request_date_time=self.shadow_date_time,
                bounds=self.bounds,
            )

            gdh_shadow_result = q.enqueue(
                utils.compute_gdh_shadow_with_tree_canopy,
                asdict(gdh_worker_data),
                on_success=notify_shadow_complete,
                on_failure=shadow_generation_failure,
                job_id=self.session_id + ":" + self.shadow_date_time,
                depends_on=gdh_buildings_shadow_dependency,
            )

            _gdh_roads_shadows_start_processing = RoadsShadowsComputationStartRequest(
                bounds=self.bounds,
                session_id=self.session_id,
                request_date_time=self.shadow_date_time,
            )

            gdh_roads_intersection_result = q.enqueue(
                utils.kickoff_gdh_roads_shadows_stats,
                asdict(_gdh_roads_shadows_start_processing),
                on_success=notify_gdh_roads_shadow_intersection_complete,
                on_failure=notify_gdh_roads_shadow_intersection_failure,
                job_id=self.session_id + ":gdh_roads_shadow",
                depends_on=[gdh_shadow_result],
            )

    # def compute_existing_buildings_shadow(self):
    #     ''' This method computes the shadow for existing or GDH buidlings '''

    #     r_url = os.getenv("ROADS_URL", None)
    #     t_url = os.getenv("TREES_URL", None)
    #     b_url = os.getenv("BUILDINGS_URL", None)
    #     try:
    #         assert r_url is not None
    #         assert t_url is not None
    #         assert b_url is not None
    #     except AssertionError as ae:
    #         print("A Roads, Canopy and a Existing Buildings GeoJSON as a URL is expected")
    #     else:
    #         # first download the trees and then compute design shadow
    #         trees_download_job = TreesDownloadRequest(bounds= self.bounds,  session_id = str(self.session_id), request_date_time=self.shadow_date_time,trees_url=t_url)
    #         trees_download_result = q.enqueue(utils.download_trees, asdict(trees_download_job), job_id = self.session_id + ":"+ self.shadow_date_time +":trees")

    #         roads_download_job = RoadsDownloadRequest(bounds= self.bounds,  session_id = str(self.session_id), request_date_time=self.shadow_date_time,roads_url=r_url)
    #         roads_download_result = q.enqueue(utils.download_roads, asdict(roads_download_job), job_id = self.session_id + ":"+ self.shadow_date_time +":roads")

    #         # # download existing buildings
    #         buildings_download_job = BuildingsDownloadRequest(bounds= self.bounds,  session_id = str(self.session_id), request_date_time=self.shadow_date_time,buildings_url=b_url)
    #         buildings_download_result = q.enqueue(utils.download_existing_buildings, asdict(buildings_download_job), job_id = self.session_id + ":"+ self.shadow_date_time +":existing_buildings")

    #         existing_buildings_shadow_dependency = Dependency(jobs=[trees_download_result, roads_download_result, buildings_download_result], allow_failure=False,enqueue_at_front=True)

    #         # generate the existing buildings Shadows
    #         existing_worker_data = ExistingBuildingsDataShadowGenerationRequest(session_id = self.session_id, request_date_time = self.shadow_date_time, bounds =self.bounds)
    #         existing_shadow_result = q.enqueue(utils.compute_existing_buildings_shadow_with_tree_canopy,asdict(existing_worker_data), on_success= existing_buildings_notify_shadow_complete, on_failure = existing_buildings_shadow_generation_failure, job_id = self.session_id + ":"+ self.shadow_date_time,  depends_on=existing_buildings_shadow_dependency)

    #         # Compute roads shadow interection based on Existing Buildings

    #         _existing_roads_shadows_start_processing = RoadsShadowsComputationStartRequest(bounds = self.bounds, session_id= self.session_id, request_date_time= self. shadow_date_time)

    #         existing_roads_intersection_result = q.enqueue(utils.kickoff_existing_buildings_roads_shadows_stats, asdict(_existing_roads_shadows_start_processing), on_success= notify_existing_roads_shadow_intersection_complete, on_failure = notify_existing_roads_shadow_intersection_failure, job_id = self.session_id + ':existing_buildings_roads_shadow' , depends_on = [existing_shadow_result])
