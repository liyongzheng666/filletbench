#pragma once
#include <map>
#include <vector>
#include <string>
#include <variant>
#include <sstream>
#include <iomanip>
#include <cmath>
struct Json {
 using Obj=std::map<std::string,Json>;using Arr=std::vector<Json>;std::variant<std::nullptr_t,bool,double,std::string,Obj,Arr> v;
 Json():v(nullptr){} Json(std::nullptr_t):v(nullptr){} Json(bool x):v(x){} Json(int x):v(double(x)){}Json(long x):v(double(x)){}Json(unsigned x):v(double(x)){}Json(unsigned long x):v(double(x)){} Json(double x):v(std::isfinite(x)?std::variant<std::nullptr_t,bool,double,std::string,Obj,Arr>(x):std::variant<std::nullptr_t,bool,double,std::string,Obj,Arr>(nullptr)){}Json(const char*x):v(std::string(x)){}Json(std::string x):v(std::move(x)){}
 static Json object(){Json j;j.v=Obj{};return j;}static Json array(){Json j;j.v=Arr{};return j;}Json& operator[](const std::string& k){if(!std::holds_alternative<Obj>(v))v=Obj{};return std::get<Obj>(v)[k];}void push(Json x){if(!std::holds_alternative<Arr>(v))v=Arr{};std::get<Arr>(v).push_back(std::move(x));}
 static std::string quote(const std::string&s){std::ostringstream o;o<<'"';for(unsigned char c:s){if(c=='"'||c=='\\')o<<'\\'<<c;else if(c=='\n')o<<"\\n";else if(c=='\r')o<<"\\r";else if(c=='\t')o<<"\\t";else if(c<32)o<<"\\u"<<std::hex<<std::setw(4)<<std::setfill('0')<<int(c)<<std::dec;else o<<c;}o<<'"';return o.str();}
 std::string dump() const {std::ostringstream o;o<<std::setprecision(17);if(std::holds_alternative<std::nullptr_t>(v))return "null";if(auto p=std::get_if<bool>(&v))return *p?"true":"false";if(auto p=std::get_if<double>(&v)){o<<*p;return o.str();}if(auto p=std::get_if<std::string>(&v))return quote(*p);if(auto p=std::get_if<Obj>(&v)){o<<'{';bool first=true;for(auto&[k,x]:*p){if(!first)o<<',';first=false;o<<quote(k)<<':'<<x.dump();}o<<'}';}else if(auto p=std::get_if<Arr>(&v)){o<<'[';for(size_t i=0;i<p->size();++i){if(i)o<<',';o<<(*p)[i].dump();}o<<']';}return o.str();}
};
