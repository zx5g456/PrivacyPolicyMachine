# XR Privacy Policy Analyzer Configuration

# OpenAI API configuration. OpenAI() reads OPENAI_API_KEY from the environment,
# matching the P2/P3 clients.
GPT_MODEL = "gpt-4o-mini"
GPT_MAX_TOKENS = 3000
GPT_TEMPERATURE = 0.1

# LLM Model General Configuration
BASE_DELAY = 1  # Initial retry delay in seconds

# Retry Configuration
MAX_RETRIES = 3

# Directory Configuration
ROOT_DIRECTORY = "./origin_pp"
DATATYPE_RESULT_DIRECTORY = "./datatype_result"
RISK_RESULT_DIRECTORY = "./risk_result"
PROGRESS_FILE = "xr_privacy_analysis_progress.json"
RISK_PROGRESS_FILE = "risk_progress.json"

# Supported file extensions for privacy policies
SUPPORTED_EXTENSIONS = [".txt", ".md", ".html"]

# XR-specific data types for analysis - Refined and focused list
XR_DATA_TYPES = [
    # Core XR Biometric Data
    "eye tracking data",
    "gaze patterns",
    "facial expressions",
    "facial recognition",
    "voice patterns",
    "biometric identifiers",
    "physiological responses",
    "heart rate data",
    "pulse data",
    "blood pressure data",
    "breathing patterns",
    "skin conductance",
    "body temperature data",
    # XR Motion and Gesture Data
    "hand gestures",
    "hand tracking",
    "body movements",
    "head tracking",
    "gesture recognition",
    # Spatial and Environmental Data
    "spatial coordinates",
    "room mapping",
    "environmental scanning",
    "room scale tracking",
    "spatial anchors",
    "3D environment data",
    "passthrough data",
    "virtual reality tracking data",
    "spatiotemporal tracking data",
    "location tracking data",
    # XR Device and Technical Data
    "device orientation",
    "field of view data",
    "interpupillary distance",
    "headset calibration data",
    "haptic feedback data",
    # XR Safety and Boundary Data
    "play area boundaries",
    "guardian system data",
    "safety boundary data",
    # XR Interaction Data
    "virtual object interactions",
    "3D interaction data",
    "avatar data",
    "virtual environment preferences",
    # XR Performance Data
    "motion sickness indicators",
    "comfort settings",
    "performance metrics",
    "frame rate data",
    "fitness performance history",
    "exercise data",
    "workout statistics",
    "activity tracking data",
    # XR Social Data
    "multiplayer interactions",
    "shared virtual spaces",
    "VR social interactions",
    "follower data",
    "social connections",
    "friend lists",
    # XR Usage Data
    "XR session duration",
    "XR application usage",
    "virtual world analytics",
    # XR Application Data
    "crash reports",
    "error logs",
    "user behavior statistics",
    "application performance data",
]

# Analysis categories specific to XR applications
ANALYSIS_CATEGORIES = [
    "XR_DATA_TYPES",
    "CHILDREN_XR",
    "REGION_XR",
    "RETENTION_XR",
    "SHARING_XR",
    "XR_TYPE_CHECKLIST",
]
