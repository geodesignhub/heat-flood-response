from dataclasses import dataclass
from typing import List
from typing import Optional

@dataclass
class ErrorResponse:
    # A class to hold error resposnes
    message: str
    code: int
    status: int

@dataclass
class BuildingData:    
    height: float
    base_height: float

@dataclass
class GeodesignhubFeatureProperties:
    sysid: int    
    description: str    
    height: float
    base_height: float
    color:str
    diagram_id:int
    building_id: str


@dataclass
class GeodesignhubDesignFeatureProperties:
    author:str
    description: str    
    height: float
    base_height: float
    color:str
    diagram_id:int
    building_id: str
    areatype:str
    min_height: float
    max_height:float


@dataclass
class GeodesignhubDiagramGeoJSON: 
    # Source: https://www.geodesignhub.com/api/#diagrams-api-diagram-detail-get
    geojson: dict
    

@dataclass
class GeodesignhubSystem:
    # Source: https://www.geodesignhub.com/api/#systems-api-systems-collection-get
    id:int
    sysname: str
    syscolor:str

@dataclass
class GeodesignhubProjectBounds:
    
    bounds: str

@dataclass
class GeodesignhubProjectCenter:    
    center: str

@dataclass
class GeodesignhubProjectData:
    systems: List[GeodesignhubSystem]
    bounds: GeodesignhubProjectBounds
    center: GeodesignhubProjectCenter

@dataclass
class DiagramShadowSuccessResponse:
    message: str
    status: int
    project_data: GeodesignhubProjectData
    diagram_geojson: GeodesignhubDiagramGeoJSON
    maptiler_key: str
    session_id: str

@dataclass
class DesignShadowSuccessResponse:
    message: str
    status: int
    project_data: GeodesignhubProjectData
    design_geojson: GeodesignhubDiagramGeoJSON
    maptiler_key: str
    session_id: str

@dataclass
class GeodesignhubDataShadowGenerationRequest:
    geojson: dict
    session_id: str
    request_date_time: str
    
@dataclass
class RoadsDownloadRequest:
    bounds: str
    session_id: str
    request_date_time: str
    roads_url: str

@dataclass
class TreesDownloadRequest:
    bounds: str
    session_id: str
    request_date_time: str
    trees_url: str


@dataclass
class ShadowsRoadsIntersectionRequest:
    roads: str
    job_id: str
    shadows: str


@dataclass
class RoadsShadowOverlap: 
    total_roads_kms: float
    shadowed_kms: float
    job_id: str
    