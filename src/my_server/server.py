# cadquery_mcp_server.py
from fastmcp import FastMCP
from smithery.decorators import smithery
import cadquery as cq
from cadquery import Vector
from cadquery.vis import show
import json
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
import os
import uvicorn
from starlette.middleware.cors import CORSMiddleware
from typing import Optional
from middleware import SmitheryConfigMiddleware


# src/main.py (continued - only add if you need configuration)

def handle_config(config: dict):
    """Handle configuration from Smithery - for backwards compatibility with stdio mode."""
    global _server_token
    if server_token := config.get('serverToken'):
        _server_token = server_token
    # You can handle other session config fields here

# Store server token only for stdio mode (backwards compatibility)
_server_token: Optional[str] = None

def get_request_config() -> dict:
    """Get full config from current request context."""
    try:
        # Access the current request context from FastMCP
        import contextvars
        
        # Try to get from request context if available
        request = contextvars.copy_context().get('request')
        if hasattr(request, 'scope') and request.scope:
            return request.scope.get('smithery_config', {})
    except:
        pass

def get_config_value(key: str, default=None):
    """Get a specific config value from current request."""
    config = get_request_config()
    return config.get(key, default)

def validate_server_access(server_token: Optional[str]) -> bool:
    """Validate server token - accepts any string including empty ones for demo."""
    # In a real app, you'd validate against your server's auth system
    # For demo purposes, we accept any non-empty token
    return server_token is not None and len(server_token.strip()) > 0 if server_token else True



@smithery.server()
def create_server():
    # 创建FastMCP服务器实例
    mcp = FastMCP("CADQuery_MCP_Server")

    # 添加初始化处理
    @mcp.on_initialize()
    async def on_initialize():
        print("MCP Server initialized successfully")
        return {
            "protocolVersion": "2025-06-18",
            "capabilities": {
                "tools": {},
                "resources": {}
            },
            "serverInfo": {
                "name": "CADQuery_MCP_Server",
                "version": "1.0.0"
            }
        }

    # 全局模型管理器
    class GlobalModelManager:
        def __init__(self):
            self.models: List[Dict] = []
            self.current_assembly = cq.Assembly()
        
        def add_model(self, name: str, shape: cq.Solid, shape_type: str, boundary: str) -> Dict:
            """添加新模型到全局装配"""
            model_info = {
                "id": len(self.models) + 1,
                "name": name,
                "type": shape_type,
                "boundary": boundary
            }
            self.models.append(model_info)
            
            # 添加到装配中
            self.current_assembly.add(shape)
            
            return model_info
        
        def get_all_models_info(self) -> List[Dict]:
            """获取所有模型的信息（不包含shape对象）"""
            return [
                {
                    "id": model["id"],
                    "type": model["type"],
                    "parameters": model.get("parameters", {}),
                    "workplane": model.get("workplane", ""),
                    "extrude_direction": model.get("extrude_direction", "")
                }
                for model in self.models
            ]
        
        def get_combined_model(self) -> cq.Assembly:
            """获取组合后的完整模型"""
            return self.current_assembly
        
        def clear_all(self):
            """清空所有模型"""
            self.models = []
            self.current_assembly = cq.Assembly()

    # 初始化全局模型管理器
    model_manager = GlobalModelManager()

    # 添加健康检查工具
    @mcp.tool()
    def health_check() -> str:
        """健康检查端点，用于验证服务器状态"""
        # 获取会话配置
        config = get_request_config()
        debug_mode = config.get('debug_mode', False)
        
        if debug_mode:
            print("Debug: Health check called")
        
        return json.dumps({
            "status": "healthy",
            "server": "CADQuery_MCP_Server",
            "tools_count": len(model_manager.models),
            "timestamp": time.time(),
            "version": "1.0.0",
            "config": config
        })

    @mcp.tool()
    def create_box_Axi_W_H(
        model_name: str,
        rect_workplane_axi: str,
        rect_origin_x1: float,
        rect_origin_x2: float,
        rect_width: float,
        rect_height: float,
        extrude_start: float,
        extrude_end: float
    ) -> str:
        """
        通过定义轴以及长宽的方式创建长方体特征
        """
        # 获取会话配置
        config = get_request_config()
        debug_mode = config.get('debug_mode', False)
        max_models = config.get('max_models', 100)
        server_token = config.get('server_token')
        
        # 验证访问权限
        if not validate_server_access(server_token):
            return json.dumps({"error": "Invalid server token"})
        
        # 检查模型数量限制
        if len(model_manager.models) >= max_models:
            return json.dumps({"error": f"已达到最大模型数量限制: {max_models}"})
        
        if debug_mode:
            print(f"Debug: Creating box {model_name} with axis {rect_workplane_axi}")
        
        # 创建工作平面
        match rect_workplane_axi:
            case "X":
                wp = cq.Workplane("YZ").workplane(origin=(extrude_start, rect_origin_x1, rect_origin_x2))
            case "Y":
                wp = cq.Workplane("XZ").workplane(origin=(rect_origin_x1, extrude_start, rect_origin_x2))
            case "Z":
                wp = cq.Workplane("XY").workplane(origin=(rect_origin_x1, rect_origin_x2, extrude_start))

        wp = wp.workplane(offset=extrude_start)
        box = wp.rect(rect_width, rect_height).extrude(extrude_end - extrude_start)
        
        if debug_mode:
            print("长方体创建完成，准备添加到模型管理器")
            
        match rect_workplane_axi:
            case "X":
                model_info = model_manager.add_model(name=model_name, shape=box, shape_type="box", boundary=f" X_boundary: {extrude_start}->{extrude_end}\n Y_boundary: {rect_origin_x1-rect_width/2}->{rect_origin_x1+rect_width/2}\n Height: {rect_origin_x2-rect_height/2}->{rect_origin_x2+rect_height/2}")
            case "Y":
                model_info = model_manager.add_model(name=model_name, shape=box, shape_type="box", boundary=f" X_boundary: {rect_origin_x1-rect_width/2}->{rect_origin_x1+rect_width/2}\n Y_boundary: {extrude_start}->{extrude_end}\n Height: {rect_origin_x2-rect_height/2}->{rect_origin_x2+rect_height/2}")
            case "Z":
                model_info = model_manager.add_model(name=model_name, shape=box, shape_type="box", boundary=f" X_boundary: {rect_origin_x1-rect_width/2}->{rect_origin_x1+rect_width/2}\n Y_boundary: {rect_origin_x2-rect_height/2}->{rect_origin_x2+rect_height/2}\n Height: {extrude_start}->{extrude_end}")

        return (
            f'{{\n'
            f'  "message": "长方体创建成功 (ID: {model_info["id"]})",\n'
            f'  "model_info": {{\n'
            f'    "模型名称": "{model_info["name"]}",\n'
            f'    "序号": {model_info["id"]},\n'
            f'    "模型类别": "{model_info["type"]}",\n'
            f'    "边界": {model_info["boundary"]}\n'
            f'  }},\n'
            f'  "total_models": {len(model_manager.models)}\n'
            f'}}'
        )

    @mcp.tool()
    def create_cylinder_Axi_R(
        model_name: str,
        circle_workplane_axi: str,
        circle_origin_x1: float,
        circle_origin_x2: float,
        circle_radius: float,
        extrude_start: float,
        extrude_end: float
    ) -> str:
        """
        通过定义轴以及半径的方式创建圆柱体特征，这种方法对于生成有明显轴向的圆柱体很有用：
        定位方法说明：
        1. 通过circle_workplane_axi参数定义待拉伸的基准平面的法向量，可选项为('X','Y','Z')，对应平面为平面'YZ'、'XZ'、'XY'
        2. 通过circle_origin_x1和circle_origin_x2定义二维平面原点位置，即初始圆的中心，在YZ平面上时，x1表示Y坐标，x2表示Z坐标，以此类推
        3. 通过circle_radius定义二维平面的圆半径
        3. 通过extrude_start和extrude_end定义拉伸的起始和结束位置，沿着平面的法向量方向拉伸
        4. model_name根据在最终cad模型中的职能进行定义
        返回: 包含模型信息的JSON字符串
        """
        # 获取会话配置
        config = get_request_config()
        debug_mode = config.get('debug_mode', False)
        max_models = config.get('max_models', 100)
        server_token = config.get('server_token')
        
        # 验证访问权限
        if not validate_server_access(server_token):
            return json.dumps({"error": "Invalid server token"})
        
        # 检查模型数量限制
        if len(model_manager.models) >= max_models:
            return json.dumps({"error": f"已达到最大模型数量限制: {max_models}"})
        
        if debug_mode:
            print(f"Debug: Creating cylinder {model_name} with axis {circle_workplane_axi}")
        
        # 创建工作平面
        match circle_workplane_axi:
            case "X":
                wp = cq.Workplane("YZ").workplane(origin=(extrude_start, circle_origin_x1, circle_origin_x2))
            case "Y":
                wp = cq.Workplane("XZ").workplane(origin=(circle_origin_x1, extrude_start, circle_origin_x2))
            case "Z":
                wp = cq.Workplane("XY").workplane(origin=(circle_origin_x1, circle_origin_x2, extrude_start))

        wp = wp.workplane(offset=extrude_start)

        cylinder = wp.circle(circle_radius).extrude(extrude_end - extrude_start)

        if debug_mode:
            print("圆柱体创建完成，准备添加到模型管理器")
        match circle_workplane_axi:
            case "X":
                model_info = model_manager.add_model(name=model_name, shape=cylinder, shape_type="cylinder", boundary=f" X_boundary: {extrude_start}->{extrude_end}\n YZ_circle_center: ({circle_origin_x1}, {circle_origin_x2})\n Radius: {circle_radius}")
            case "Y":
                model_info = model_manager.add_model(name=model_name, shape=cylinder, shape_type="cylinder", boundary=f" Y_boundary: {extrude_start}->{extrude_end}\n XZ_circle_center: ({circle_origin_x1}, {circle_origin_x2})\n Radius: {circle_radius}")
            case "Z":
                model_info = model_manager.add_model(name=model_name, shape=cylinder, shape_type="cylinder", boundary=f" Z_boundary: {extrude_start}->{extrude_end}\n XY_circle_center: ({circle_origin_x1}, {circle_origin_x2})\n Radius: {circle_radius}")
            
        return (
            f'{{\n'
            f'  "message": "圆柱体创建成功 (ID: {model_info["id"]})",\n'
            f'  "model_info": {{\n'
            f'    "模型名称": "{model_info["name"]}",\n'
            f'    "序号": {model_info["id"]},\n'
            f'    "模型类别": "{model_info["type"]}",\n'
            f'    "边界": {model_info["boundary"]}\n'
            f'  }},\n'
            f'  "total_models": {len(model_manager.models)}\n'
            f'}}'
        )

    @mcp.tool()
    def visualize_models(
        width: int = 800,
        height: int = 600,
        screenshot: Optional[str] = None,
        interact: bool = True
    ) -> str:
        """
        可视化当前所有模型
        
        参数:
        - width: 窗口宽度
        - height: 窗口高度
        - screenshot: 截图保存路径(可选)
        - interact: 是否交互模式
        
        返回: 包含模型信息和可视化状态的JSON字符串
        """
        # 获取会话配置
        config = get_request_config()
        debug_mode = config.get('debug_mode', False)
        max_models = config.get('max_models', 100)
        server_token = config.get('server_token')
        
        # 验证访问权限
        if not validate_server_access(server_token):
            return json.dumps({"error": "Invalid server token"})
        
        if not model_manager.models:
            return json.dumps({
                "message": "当前没有可显示的模型",
                "models_count": 0
            }, ensure_ascii=False)
        
        try:
            # 获取组合模型
            assembly = model_manager.get_combined_model()
            
            # 准备显示参数
            show_params = {
                "width": width,
                "height": height,
                "interact": interact
            }
            
            if screenshot:
                show_params["screenshot"] = screenshot
            
            # 显示模型
            show(assembly)
            
            return (
            f'{{\n'
            f'  "message": "模型可视化成功",\n'
            f'  "models_info": {model_manager.get_all_models_info()},\n'
            f'  "models_count": {len(model_manager.models)},\n'
            f'  "visualization_params": {show_params}\n'
            f'}}'
            )
            
        except Exception as e:
            return (
                f'{{\n'
                f'  "message": "可视化失败: {str(e)}",\n'
                f'  "error": "{str(e)}"\n'
                f'}}'
            )

    @mcp.tool()
    def clear_models() -> str:
        """
        清空所有模型
        
        返回: 操作结果
        """
        # 获取会话配置
        config = get_request_config()
        debug_mode = config.get('debug_mode', False)
        max_models = config.get('max_models', 100)
        server_token = config.get('server_token')
        
        # 验证访问权限
        if not validate_server_access(server_token):
            return json.dumps({"error": "Invalid server token"})
        
        model_manager.clear_all()
        print("所有模型已清空")
        return (
            f'"message": "所有模型已清空",\n'
            f'"models_count": 0\n'
            )

    # 返回配置好的服务器
    return mcp

if __name__ == "__main__":
    # 本地开发时直接运行服务器
    server = create_server()
    server.run(transport="sse", port=8095)