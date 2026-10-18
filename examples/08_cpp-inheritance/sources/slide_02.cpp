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
r.kind();
r.speak();
p->speak();
r.Base::speak();
Base copy = d;
copy.speak();
assert(std::string(r.kind()) == "Base"); assert(std::string(r.speak()) == "Derived"); assert(std::string(copy.speak()) == "Base");
}
