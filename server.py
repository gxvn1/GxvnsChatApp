from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import json
from datetime import datetime
import os
from typing import Dict
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store active connections and user credentials
active_connections: Dict[str, WebSocket] = {}
user_credentials: Dict[str, str] = {}

class ChatServer:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.user_credentials: Dict[str, str] = {}
        self.users_dir = "server_data"
        if not os.path.exists(self.users_dir):
            os.makedirs(self.users_dir)
        self.users_file = os.path.join(self.users_dir, "users.json")
        self.load_user_data()

    def load_user_data(self):
        """Load user data from file or create empty data"""
        try:
            with open(self.users_file, 'r') as f:
                self.user_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.user_data = {}  # {username: {'password': hash, 'friends': []}}
            self.save_user_data()

    def save_user_data(self):
        """Save user data to file"""
        with open(self.users_file, 'w') as f:
            json.dump(self.user_data, f)

    async def register_user(self, websocket: WebSocket, data: dict) -> dict:
        """Handle user registration"""
        username = data.get('username')
        password = data.get('password')
        
        if username in self.user_credentials:
            return {'type': 'register_response', 'success': False, 'message': 'Username already exists'}
        
        # Hash password
        hashed_password = password
        
        # Store user data
        self.user_credentials[username] = hashed_password
        self.user_data[username] = {
            'password': hashed_password,
            'friends': []
        }
        self.save_user_data()
        
        return {'type': 'register_response', 'success': True}

    async def login_user(self, websocket: WebSocket, data: dict) -> dict:
        """Handle user login"""
        username = data.get('username')
        password = data.get('password')
        
        if username not in self.user_credentials:
            return {'type': 'login_response', 'success': False, 'message': 'Invalid username or password'}
        
        if self.user_credentials[username] != password:
            return {'type': 'login_response', 'success': False, 'message': 'Invalid username or password'}
        
        # Remove old connection if exists
        if username in active_connections:
            try:
                await active_connections[username].close()
            except:
                pass
        
        active_connections[username] = websocket
        
        return {
            'type': 'login_response',
            'success': True,
            'username': username,
            'friends': self.user_data[username]['friends']
        }

    async def broadcast(self, message: dict, sender: WebSocket = None):
        """Broadcast message to all connected clients except sender"""
        for connection in active_connections.values():
            if connection != sender:
                await connection.send_json(message)

    async def send_direct_message(self, recipient: str, message: dict):
        """Send message to specific user"""
        for username, ws in active_connections.items():
            if username == recipient:
                await ws.send_json(message)
                break

    async def broadcast_to_group(self, group_name: str, message: dict, sender: WebSocket = None):
        """Broadcast message to all members of a group except sender"""
        group_members = self.groups.get(group_name, [])
        for username in group_members:
            if username != self.active_connections.get(sender):
                await self.send_direct_message(username, message)

    async def handle_call_request(self, message: dict):
        """Handle call request"""
        recipient = message['to']
        await self.send_direct_message(recipient, message)

    async def handle_screen_share(self, message: dict):
        """Handle screen share"""
        recipient = message['to']
        await self.send_direct_message(recipient, message)

    async def handle_create_group(self, message: dict):
        """Handle create group"""
        group_name = message['group_name']
        members = message['members']
        self.groups[group_name] = members
        group_created = {
            'type': 'group_created',
            'group_name': group_name,
            'members': members,
            'creator': message['username']
        }
        await self.broadcast_to_group(group_name, group_created)

    async def handle_add_friend(self, message: dict):
        """Handle add friend"""
        friend_username = message['friend']
        if friend_username in self.user_data:
            self.user_data[message['username']]['friends'].append(friend_username)
            self.user_data[friend_username]['friends'].append(message['username'])
            self.save_user_data()
            friend_added = {
                'type': 'friend_added',
                'friend': friend_username
            }
            await self.send_direct_message(message['username'], friend_added)
            await self.send_direct_message(friend_username, {
                'type': 'friend_request',
                'from': message['username']
            })

chat_server = ChatServer()

@app.get("/")
async def root():
    """Health check endpoint"""
    return {"status": "ok", "message": "GxvnsChatApp server is running"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    username = None
    logger.info("New WebSocket connection established")
    
    try:
        while True:
            try:
                data = await websocket.receive_json()
                logger.info(f"Received message: {data}")
                
                if data['type'] == 'register':
                    response = await chat_server.register_user(websocket, data)
                    await websocket.send_json(response)
                
                elif data['type'] == 'login':
                    response = await chat_server.login_user(websocket, data)
                    await websocket.send_json(response)
                    if response['success']:
                        username = response['username']
                        # Notify others
                        await chat_server.broadcast({
                            'type': 'user_online',
                            'username': username
                        }, websocket)
                
                elif data['type'] == 'message':
                    if data.get('group'):
                        await chat_server.broadcast_to_group(data['group'], data, websocket)
                    elif data.get('to'):
                        # Direct message
                        await chat_server.send_direct_message(data['to'], data)
                    else:
                        # Broadcast message
                        await chat_server.broadcast(data, websocket)
                
                elif data['type'] == 'call_request':
                    await chat_server.handle_call_request(data)
                
                elif data['type'] == 'screen_share':
                    await chat_server.handle_screen_share(data)
                
                elif data['type'] == 'create_group':
                    await chat_server.handle_create_group({'group_name': data['group_name'], 'members': data['members'], 'username': username})
                
                elif data['type'] == 'add_friend':
                    await chat_server.handle_add_friend({'friend': data['friend'], 'username': username})
            
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON message: {e}")
                continue
            except Exception as e:
                logger.error(f"Error processing message: {e}")
                continue
    
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for user: {username}")
        if username and username in active_connections:
            del active_connections[username]
            await chat_server.broadcast({
                'type': 'user_offline',
                'username': username
            })
    except Exception as e:
        logger.error(f"Error in websocket_endpoint: {e}")
        if username and username in active_connections:
            del active_connections[username]

async def broadcast_message(message: dict, exclude: str = None):
    """Send message to all connected clients except the sender"""
    disconnected_users = []
    
    for username, connection in active_connections.items():
        if username != exclude:
            try:
                await connection.send_json(message)
                logger.info(f"Message broadcast to {username}")
            except Exception as e:
                logger.error(f"Error broadcasting to {username}: {e}")
                disconnected_users.append(username)
    
    # Clean up disconnected users
    for username in disconnected_users:
        if username in active_connections:
            del active_connections[username]
            logger.info(f"Removed disconnected user: {username}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8765))
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
        timeout_keep_alive=60,
        ws_ping_interval=20,
        ws_ping_timeout=20
    )
