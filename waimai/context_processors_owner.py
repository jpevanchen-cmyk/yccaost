# 页面上下文：访客追踪、服务器设置私人插件导航

from django.conf import settings


def visitor_tracking(request):
    """未登录访客统计：把当前页面记录编号传给模板"""
    return {
        'yc_page_view_id': getattr(request, 'yc_page_view_id', '') or '',
        'yc_track_visitor': bool(getattr(request, 'yc_track_visitor', False)),
    }


def server_plugin_nav(request):
    """服务器设置页：私人工具包额外导航"""
    if not getattr(settings, 'YECAO_OWNER_TOOLKIT_ENABLED', False):
        return {'server_plugin_nav': []}
    try:
        from waimai.server_plugin_runtime.registry import server_manager_nav_items

        return {'server_plugin_nav': server_manager_nav_items()}
    except Exception:
        return {'server_plugin_nav': []}
