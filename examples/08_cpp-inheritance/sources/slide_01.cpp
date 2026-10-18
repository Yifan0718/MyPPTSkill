#include <iostream>
#include <string>
#include <cassert>
struct Base {
  int id = 7;
  const char* kind() const { return "Base"; }
  virtual const char* speak() const {
    return "Base";
  }
  virtual ~Base() = default;
};
struct Derived : public Base {
  int score = 90;
  const char* kind() const { return "Derived"; }
  const char* speak() const override {
    return "Derived";
  }
};
int main() {
Derived d;
Base& r = d;
Base* p = &d;
assert(&r == p); assert(r.id == 7); assert(d.score == 90);
}
