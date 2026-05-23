#include "ring_buffer.h"

void ring_buffer_init(ring_buffer_t* buffer, uint8_t* storage, size_t capacity) {
  buffer->data = storage;
  buffer->capacity = capacity;
  buffer->head = 0;
  buffer->tail = 0;
  buffer->size = 0;
}

void ring_buffer_clear(ring_buffer_t* buffer) {
  buffer->head = 0;
  buffer->tail = 0;
  buffer->size = 0;
}

size_t ring_buffer_size(const ring_buffer_t* buffer) { return buffer->size; }

size_t ring_buffer_available(const ring_buffer_t* buffer) {
  return buffer->capacity - buffer->size;
}

bool ring_buffer_empty(const ring_buffer_t* buffer) { return buffer->size == 0; }

size_t ring_buffer_write(ring_buffer_t* buffer, const uint8_t* src, size_t len) {
  size_t written = 0;

  while (written < len && buffer->size < buffer->capacity) {
    buffer->data[buffer->head] = src[written];
    buffer->head = (buffer->head + 1U) % buffer->capacity;
    buffer->size++;
    written++;
  }

  return written;
}

size_t ring_buffer_read(ring_buffer_t* buffer, uint8_t* dst, size_t len) {
  size_t read = 0;

  while (read < len && buffer->size > 0U) {
    dst[read] = buffer->data[buffer->tail];
    buffer->tail = (buffer->tail + 1U) % buffer->capacity;
    buffer->size--;
    read++;
  }

  return read;
}
