#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <vector>

extern "C" {
#include "../esp8266_sdk/project/include/ring_buffer.h"
}

namespace {

void expect(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << "\n";
    std::exit(1);
  }
}

void writes_and_reads_in_order() {
  uint8_t storage[8] = {0};
  ring_buffer_t buffer;
  ring_buffer_init(&buffer, storage, sizeof(storage));

  const uint8_t input[] = {1, 2, 3, 4};
  uint8_t output[4] = {0};

  expect(ring_buffer_write(&buffer, input, sizeof(input)) == sizeof(input),
         "write full input");
  expect(ring_buffer_read(&buffer, output, sizeof(output)) == sizeof(output),
         "read full output");

  for (std::size_t i = 0; i < sizeof(input); ++i) {
    expect(output[i] == input[i], "preserve byte order");
  }
}

void wraps_correctly() {
  uint8_t storage[4] = {0};
  ring_buffer_t buffer;
  ring_buffer_init(&buffer, storage, sizeof(storage));

  const uint8_t first[] = {10, 11, 12};
  const uint8_t second[] = {20, 21};
  uint8_t output[4] = {0};
  uint8_t scratch[2] = {0};

  expect(ring_buffer_write(&buffer, first, sizeof(first)) == sizeof(first),
         "write initial bytes");
  expect(ring_buffer_read(&buffer, scratch, 2) == 2, "read prefix");
  expect(ring_buffer_write(&buffer, second, sizeof(second)) == sizeof(second),
         "wrap write");
  expect(ring_buffer_read(&buffer, output, 3) == 3, "read wrapped bytes");

  expect(output[0] == 12, "wrapped read keeps remaining first byte");
  expect(output[1] == 20, "wrapped read keeps first wrapped byte");
  expect(output[2] == 21, "wrapped read keeps second wrapped byte");
}

void caps_at_capacity() {
  uint8_t storage[3] = {0};
  ring_buffer_t buffer;
  ring_buffer_init(&buffer, storage, sizeof(storage));

  const uint8_t input[] = {1, 2, 3, 4, 5};
  expect(ring_buffer_write(&buffer, input, sizeof(input)) == 3,
         "truncate write at capacity");
  expect(ring_buffer_size(&buffer) == 3, "size equals capacity after overflow write");
}

}  // namespace

int main() {
  writes_and_reads_in_order();
  wraps_correctly();
  caps_at_capacity();
  std::cout << "ring_buffer tests passed\n";
  return 0;
}
