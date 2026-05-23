#ifndef TUNA_RING_BUFFER_H
#define TUNA_RING_BUFFER_H

#if defined(__has_include)
#if __has_include(<c_types.h>)
#include <c_types.h>
#else
#include <stdint.h>
#endif
#else
#include <stdint.h>
#endif

#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
  uint8_t* data;
  size_t capacity;
  size_t head;
  size_t tail;
  size_t size;
} ring_buffer_t;

void ring_buffer_init(ring_buffer_t* buffer, uint8_t* storage, size_t capacity);
void ring_buffer_clear(ring_buffer_t* buffer);
size_t ring_buffer_size(const ring_buffer_t* buffer);
size_t ring_buffer_available(const ring_buffer_t* buffer);
bool ring_buffer_empty(const ring_buffer_t* buffer);
size_t ring_buffer_write(ring_buffer_t* buffer, const uint8_t* src, size_t len);
size_t ring_buffer_read(ring_buffer_t* buffer, uint8_t* dst, size_t len);

#ifdef __cplusplus
}
#endif

#endif  // TUNA_RING_BUFFER_H
