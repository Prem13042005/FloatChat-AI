import {
  sendChatMessage,
  getConversations,
  deleteConversation,
} from "./api";

export {
  sendChatMessage,
  getConversations,
  deleteConversation,
};

export async function getConversation(id) {
  return { id, messages: [] };
}