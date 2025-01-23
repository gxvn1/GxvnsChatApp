import customtkinter as ctk
import json
import websockets
import asyncio
import threading
import queue
from datetime import datetime
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ChatClient(ctk.CTk):
    def __init__(self, username, ws_url):
        super().__init__()
        
        # Window setup
        self.title(f"GxvnsChatApp - {username}")
        self.geometry("800x600")
        
        # Store username and websocket URL
        self.username = username
        self.ws_url = ws_url
        
        logger.info(f"Chat client connecting to: {self.ws_url}")
        
        # Message queue for thread-safe updates
        self.message_queue = queue.Queue()
        
        # Create main container
        self.main_container = ctk.CTkFrame(self)
        self.main_container.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Chat display
        self.chat_display = ctk.CTkTextbox(self.main_container)
        self.chat_display.pack(fill="both", expand=True, padx=10, pady=(10, 20))
        self.chat_display.configure(state="disabled")
        
        # Message input frame
        self.input_frame = ctk.CTkFrame(self.main_container)
        self.input_frame.pack(fill="x", padx=10, pady=(0, 10))
        
        # Message input
        self.message_input = ctk.CTkEntry(
            self.input_frame,
            placeholder_text="Type your message..."
        )
        self.message_input.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.message_input.bind("<Return>", self.send_message)
        
        # Send button
        self.send_button = ctk.CTkButton(
            self.input_frame,
            text="Send",
            command=self.send_message
        )
        self.send_button.pack(side="right")
        
        # Status label
        self.status_label = ctk.CTkLabel(
            self.main_container,
            text="Connecting...",
            text_color="orange"
        )
        self.status_label.pack(pady=5)
        
        # Websocket connection
        self.websocket = None
        self.reconnect_delay = 1  # Start with 1 second delay
        self.max_reconnect_delay = 30  # Maximum delay of 30 seconds
        self.connected = False
        
        # Start websocket connection
        self.start_websocket()
        
        # Start message processing
        self.after(100, self.process_message_queue)
    
    def process_message_queue(self):
        """Process messages from the queue and update GUI"""
        try:
            while True:
                message = self.message_queue.get_nowait()
                if isinstance(message, tuple):
                    if message[0] == "STATUS":
                        self.status_label.configure(text=message[1], text_color=message[2])
                    elif message[0] == "CHAT":
                        self.add_message(message[1])
                else:
                    self.add_message(str(message))
        except queue.Empty:
            pass
        finally:
            self.after(100, self.process_message_queue)
    
    def add_message(self, message):
        """Add a message to the chat display"""
        self.chat_display.configure(state="normal")
        self.chat_display.insert("end", f"{message}\n")
        self.chat_display.see("end")
        self.chat_display.configure(state="disabled")
    
    def send_message(self, event=None):
        """Send a message to the server"""
        message = self.message_input.get().strip()
        if not message:
            return
        
        # Clear input
        self.message_input.delete(0, "end")
        
        if not self.connected:
            self.message_queue.put(("STATUS", "Not connected to server. Message will be sent when connected.", "orange"))
            return
        
        # Send message
        asyncio.run_coroutine_threadsafe(
            self.send_ws_message(message),
            self.event_loop
        )
    
    async def send_ws_message(self, message):
        """Send a message through websocket"""
        if not self.websocket:
            self.message_queue.put(("STATUS", "Not connected to server", "red"))
            return
        
        try:
            await self.websocket.send(json.dumps({
                'type': 'message',
                'username': self.username,
                'content': message,
                'timestamp': datetime.now().isoformat()
            }))
            # Reset reconnect delay on successful send
            self.reconnect_delay = 1
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            self.message_queue.put(("STATUS", f"Error sending message: {e}", "red"))
            self.connected = False
            # Force reconnection
            if self.websocket:
                try:
                    await self.websocket.close()
                except:
                    pass
                self.websocket = None
    
    def start_websocket(self):
        """Start websocket connection in a separate thread"""
        def run_async():
            self.event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.event_loop)
            
            try:
                self.event_loop.run_until_complete(self.websocket_loop())
            except Exception as e:
                logger.error(f"Websocket error: {e}")
                self.message_queue.put(("STATUS", f"Connection error: {e}", "red"))
                self.connected = False
            finally:
                self.event_loop.close()
        
        thread = threading.Thread(target=run_async, daemon=True)
        thread.start()
    
    async def websocket_loop(self):
        """Main websocket loop"""
        while True:
            try:
                logger.info(f"Connecting to {self.ws_url}")
                async with websockets.connect(
                    self.ws_url,
                    ssl=True if 'wss://' in self.ws_url else False,
                    ping_interval=20,  # Send ping every 20 seconds
                    ping_timeout=10,   # Wait 10 seconds for pong
                    close_timeout=10,  # Wait 10 seconds for close
                    max_size=10_000_000,  # 10MB max message size
                    compression=None,  # Disable compression
                    max_queue=32  # Limit message queue size
                ) as websocket:
                    self.websocket = websocket
                    self.connected = True
                    self.message_queue.put(("STATUS", "Connected", "green"))
                    
                    # Send join message
                    await websocket.send(json.dumps({
                        'type': 'join',
                        'username': self.username
                    }))
                    
                    # Reset reconnect delay on successful connection
                    self.reconnect_delay = 1
                    
                    # Receive messages
                    while True:
                        try:
                            message = await websocket.recv()
                            data = json.loads(message)
                            
                            if data['type'] == 'message':
                                timestamp = datetime.fromisoformat(data['timestamp']).strftime("%H:%M:%S")
                                formatted_message = f"[{timestamp}] {data['username']}: {data['content']}"
                                self.message_queue.put(("CHAT", formatted_message))
                            elif data['type'] == 'system':
                                self.message_queue.put(("CHAT", f"System: {data['content']}"))
                        except json.JSONDecodeError:
                            logger.error(f"Invalid message format: {message}")
                            continue
                        except websockets.ConnectionClosed:
                            logger.info("Connection closed, reconnecting...")
                            break
                        except Exception as e:
                            logger.error(f"Error receiving message: {e}")
                            break
            
            except websockets.exceptions.ConnectionClosed:
                self.websocket = None
                self.connected = False
                self.message_queue.put(("STATUS", "Disconnected. Reconnecting...", "orange"))
            
            except Exception as e:
                self.websocket = None
                self.connected = False
                logger.error(f"Websocket error: {e}")
                self.message_queue.put(("STATUS", f"Error: {e}", "red"))
            
            # Wait before reconnecting with exponential backoff
            await asyncio.sleep(self.reconnect_delay)
            self.reconnect_delay = min(self.reconnect_delay * 2, self.max_reconnect_delay)

if __name__ == "__main__":
    app = ChatClient("username", "wss://localhost:8765")
    app.mainloop()
