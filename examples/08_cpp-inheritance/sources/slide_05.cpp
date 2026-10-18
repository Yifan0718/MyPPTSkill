#include <iostream>
#include <string>
#include <cassert>
struct A {
  virtual const char* f() const { return "A"; }
  virtual ~A() = default;
};
struct B : virtual A {
  const char* f() const override { return "B"; }
};
struct C : virtual A {
  const char* f() const override { return "C"; }
};
struct D : B, C {
  const char* f() const override { return "D"; }
};
int main() {
D d;
d.B::f();  // returns "B"
A& a=d; B& b=d; C& c=d; assert(std::string(a.f()) == "D"); assert(std::string(b.f()) == "D"); assert(std::string(c.f()) == "D"); assert(std::string(d.B::f()) == "B");
}
