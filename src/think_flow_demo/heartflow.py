from .current_mind import SubHeartflow

class SubHeartflowManager:
    def __init__(self):
        self._subheartflows = {}
    
    def create_subheartflow(self, observe_chat_id):
        """创建一个新的SubHeartflow实例"""
        if observe_chat_id not in self._subheartflows:
            subheartflow = SubHeartflow()
            subheartflow.assign_observe(observe_chat_id)
            subheartflow.subheartflow_start_working()
            self._subheartflows[observe_chat_id] = subheartflow
        return self._subheartflows[observe_chat_id]
    
    def get_subheartflow(self, observe_chat_id):
        """获取指定ID的SubHeartflow实例"""
        return self._subheartflows.get(observe_chat_id)

# 创建一个全局的管理器实例
subheartflow_manager = SubHeartflowManager() 