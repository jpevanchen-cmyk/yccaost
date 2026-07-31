# 新版新手体验：模块级常量（与旧版 storage key 区分，避免并行运行时串线）

URL_PREFIX = '/experience/'

WELCOME_SEEN_KEY = 'yc_experience_welcome_seen'
SKIP_HINT_SEEN_KEY = 'yc_experience_skip_btn_hint_seen'
SESSION_TRACK_KEY = 'yc_experience_track'
SESSION_MAJOR_KEY = 'yc_experience_major'
SESSION_MICRO_KEY = 'yc_experience_micro'

# 小步自动前进秒数
AUTO_ADVANCE_SECONDS = 8
AUTO_ADVANCE_SECONDS_TYPE_DEMO = 12

# URL 查询参数（不用旧版 yc_tour，避免与旧引导同时触发）
URL_FLAG = 'exp'
URL_TRACK = 'exp_track'
URL_MAJOR = 'exp_major'
URL_MICRO = 'exp_micro'
